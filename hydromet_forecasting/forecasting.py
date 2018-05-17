import datetime

import enum
import pandas
from numpy import nan, array, isnan, full, nanmean
from sklearn.base import clone
from sklearn.model_selection import KFold

from hydromet_forecasting.timeseries import FixedIndexTimeseries
from hydromet_forecasting.evaluating import Evaluator

from sklearn import preprocessing
from timeit import default_timer as timer

from stldecompose import decompose as decomp

class RegressionModel(object):
    """Sets up the Predictor Model from sklearn, etc.

    Workflow:
        1. RegressionModel.SupportedModels.list_models(): returns dictionary of available models as name,value pairs
        2. model=RegressionModel.build_regression_model(RegressionModel.SupportedModels(value)): imports necessary classes (sklearn etc.)
        3. model.selectable_parameters: dictionary of possible parameters as parameter_type and "list of possible value" pairs.
           model.default_parameters: dictionary of default parameters as parameter_type and default value pairs.
        4. configured_model=model.configure(parameters): returns configured model with parameters.

    Attributes:
        default_parameters: dictionary of default parameters as parameter_type and default value pairs.
        selectable_parameters: dictionary of parameters as parameter_type and a list of possible values [v1,v2,v3,v4,...]
    """

    def __init__(self, model_class, selectable_parameters, default_parameters):
        self.model_class = model_class
        self.selectable_parameters = selectable_parameters
        self.default_parameters = default_parameters

    def configure(self, parameters=None):
        """Initialises model with parameters

            check Instance.selectable_parameters for possible parameters.

            Args:
                parameters: When no parameters are given, default parameters as defined in Instance.default_parameters are used.

            Returns:
                configured model object

            Raises:
                ValueError: when any parameter in parameters is invalid for this specific model.
                    """
        if parameters is None:
            return self.model_class(**self.default_parameters)
        else:
            for key in self.default_parameters:
                if not key in parameters.keys():
                    parameters.update({key: self.default_parameters[key]})
                else:
                    if not any(map(lambda x: x is parameters[key],self.selectable_parameters[key])):
                        raise ValueError("The given value for %s must be a member of the class attribte selectable parameters." %(key))

            return self.model_class(**parameters)

    class SupportedModels(enum.Enum):
        """Enum class for available models:

            list_models(): Returns: dictionary of available models as name,value pairs """

        LinearRegression = 1
        ExtraTreesRegressor = 2
        SGDRegressor = 3
        AdaBoostRegressor = 4
        MLPRegressor = 5

        @classmethod
        def list_models(self):
            out = dict()
            for model in (self):
                out[model.name] = model.value
            return out

    @classmethod
    def build_regression_model(cls, model):
        """Returns an instance of RegressionModel

            Args:
                model: An instance of RegressionModel.SupportedModels

            Returns:
                instance of RegressionModel

            Raises:
                None
                    """

        if model == cls.SupportedModels.LinearRegression:
            from sklearn import linear_model
            return cls(linear_model.LinearRegression,
                       {'fit_intercept': [True, False]},
                       {'fit_intercept': True})
        elif model == cls.SupportedModels.ExtraTreesRegressor:
            from sklearn import ensemble
            return cls(ensemble.ExtraTreesRegressor,
                       {'n_estimators': range(1, 41, 1),
                        'random_state': range(1,10)},
                       {'n_estimators': 10,
                        'random_state': 1})
        elif model == cls.SupportedModels.SGDRegressor:
            from sklearn import linear_model
            return cls(linear_model.SGDRegressor,
                       {'loss': ['squared_loss', 'huber', 'epsilon_insensitive','squared_epsilon_insensitive'],
                        'penalty': ['none', 'l2', 'l1', 'elasticnet']},
                       {'loss': 'squared_loss',
                        'penalty': 'l2'})
        elif model == cls.SupportedModels.AdaBoostRegressor:
            from sklearn import ensemble
            return cls(ensemble.AdaBoostRegressor,
                       {'base_estimator': ensemble.ExtraTreesRegressor(n_estimators=20),
                        'n_estimators': range(1, 41, 1),
                        'random_state': range(1,10)},
                       {'base_estimator': ensemble.ExtraTreesRegressor(n_estimators=20),
                        'n_estimators': 40,
                        'random_state': 1})

        elif model == cls.SupportedModels.MLPRegressor:
            from sklearn import neural_network
            return cls(neural_network.MLPRegressor,
                       {'hidden_layer_sizes': range(1, 1000, 10),
                        'activation': ['identity', 'logistic', 'tanh', 'relu']},
                       {'hidden_layer_sizes': 10,
                        'activation': 'logistic'})



class Forecaster(object):
    """Forecasting class for timeseries that can be handled/read by FixedIndexTimeseries.

    This class enables the complete workflow from setting up a timeseries model, training, evaluating
    and forecasting values. It should work with all machine learning objects that know the methods fit() and predict().
    It was designed to work with the FixedIndexTimeseries class which handles
    timeseries that have annual periodicity. In that sense, FixedIndex means, that each year has the same number of
    periods and that every period takes the same position in every year, e.g. monthes or semi-monthes etc. It does
    not work for timeseries with periods of strict length and as such, might overlap New Year.
    However, if the option multimodel is set to False, it can work with arbitrary timeseries that are handled by a class
    that replicates the methods in FixedIndexDateUtil.

    Attributes:
        trainingdates: a list of datetime.date objects of the periods whcih where used for training. Is None before training
        evaluator: An Evaluator object of the current training state of the Forecaster instance. Is None before training
    """

    def __init__(self, model, y, X, laglength, lag=0, multimodel=True, decompose=False):
        """Initialising the Forecaster Object

            Args:
                model: A model object that knows the method fit() and predict() for
                        a targetvector y and a feature array X
                y: A FixedIndexTimeseries Instance that is the target data
                X: A list of FixedIndexTimeseries Instances that represent the feature data
                laglength: A list of integers that define the number of past periods that are used from the feature set.
                        Must have the same length as X
                lag: (int): when negative: the difference in days between forecasting date and the first day of the forecasted period (backwards in time)
                            when positive: the difference in days between forecasting date and the first day of the period preceding the forecasted period (forward in time)
                            Example:
                                forecasted, decadal period is: 11.10-20.10,
                                lag=0, laglength=1: The forecast is done on 11.10. The period 1.10 to 10.10 is used as feature.
                                lag=-4, laglength=2: The forecast is done on 7.10. The periods 21.9-30.9 and 11.9-20.9 is used as feature
                                lag=3, laglength=1: The forecast is done on 4.10. The period 21.9 to 30.9  is used as feature.
                multimode: boolean. If true, a individual model is trained for each period of the year. Makes sense when the
                            timeseries have annual periodicity in order to differentiate seasonality.

            Returns:
                A Forecaster object with the methods train and predict

            Raises:
                ValueError: When the list "laglength" is of different length than the list X.
            """

        self._model = model
        self._multimodel = multimodel

        if not self._multimodel:
            self._maxindex = 1
            self._model = [self._model]
        else:
            self._maxindex = y.maxindex
            self._model = [clone(self._model) for i in range(self._maxindex)]


        self._decompose = decompose
        self._seasonal = [0 for i in range(y.maxindex)]

        self._y = y
        self._y.timeseries.columns = ["target"]

        if type(X) is not list:
            self._X = [X]
        else:
            self._X = X

        self._X_type = [x.mode for x in self._X]

        self._lag = -lag # switches the sign of lag as argument, makes it easier to understand

        if type(laglength) is not list:
            self._laglength = [laglength]
        else:
            self._laglength = laglength

        if not len(self._laglength) == len(X):
            raise ValueError("The arguments laglength and X must be lists of the same length")


        self._y_scaler = [preprocessing.StandardScaler() for i in range(self._maxindex)]
        self._X_scaler = [preprocessing.StandardScaler() for i in range(self._maxindex)]

        assert len(self._X) > 0, "predictor dataset must contain at least one feature"

        self.trainingdates = None
        self.evaluator = None

    def _aggregate_featuredates(self, targetdate):
        """Given a targetdate, returns the list of required dates from the featuresets.

            Decadal forecast, lag 0, laglength 2:
            targetdate=datetime.date(2017,8,21) --> [datetime.date(2017,8,11),datetime.date(2017,8,1)]

            Args:
                targetdate: a datetime.date that is member of the targetperiod.

            Returns:
                A list of lists with datetime.date objects in the order of the featureset.

            Raises:
                None
            """
        if self._lag < 0:
            targetdate = self._y.shift_date_by_period(targetdate, -1)
        targetdate = self._y.shift_date_by_period(targetdate, 0) - datetime.timedelta(self._lag)
        featuredates = []
        for i, x in enumerate(self._X):
            x_targetdate = x.shift_date_by_period(targetdate, 0)
            dates = []
            for shift in range(0, self._laglength[i]):
                dates.append(x.shift_date_by_period(targetdate, -(1 + shift)))
            featuredates.append(dates)
        return featuredates

    def _aggregate_features(self, featuredates, X):
        """Returns a 1D array of features for all dates in featuredates and features in X.

            The output array is in the order: feature1_t-1,feature1_t-2,feature1_t-3,feature2_t-1,feature2_t-2, and so on...

            Args:
                featuredates: A list of lists with the dates for which the data from X should be extracted
                X: A list of FixedIndexTimeseriesobjects. Its length must correspond to the length of 1st-level list of featuredates.

            Returns:
                An array with feature values

            Raises:
                None
            """

        X_values = full(sum(self._laglength), nan)
        k = 0

        for i, x in enumerate(X):
            try:
                ts = x.timeseries.reindex(featuredates[i]) # avoids the FutureWarning by pandas
                X_values[k:k + self._laglength[i]] = ts[featuredates[i]].values
            except KeyError:
                pass
            k = k + self._laglength[i]
        return X_values

    def train(self, y=None):
        """Trains the model with X and y as training set

            Args:
                y: A FixedIndexTimeseries instance that contains the target data on which the model shall be trained.
                    Is meant to be used for cross validation.
                    Default: the complete available dataset given when the instance was initialised.

            Returns:
                None

            Raises:
                InsufficientData: is raised when there is not enough data to train the model for one complete year.
            """

        if not y:
            y = self._y

        freq = len(self._seasonal)
        if self._decompose and freq>1: #TODO: Warning or not?
            dec = decomp(y.timeseries.values, period=freq)
            y = FixedIndexTimeseries(pandas.Series(dec.resid+dec.trend, index=y.timeseries.index), mode=y.mode)
            seasonal = FixedIndexTimeseries(pandas.Series(dec.seasonal, index=y.timeseries.index), mode=y.mode)
            self._seasonal = [nanmean(seasonal.data_by_index(i+1)) for i in range(freq)]

        X_list = [[] for i in range(self._maxindex)]
        y_list = [[] for i in range(self._maxindex)]
        trainingdate_list = []

        for index, y_value in y.timeseries.iteritems():
            if self._multimodel:
                annual_index = y.convert_to_annual_index(index)
            else:
                annual_index = 1

            featuredates = self._aggregate_featuredates(index)

            X_values = self._aggregate_features(featuredates, self._X)

            if not isnan(y_value) and not isnan(X_values).any():
                y_list[annual_index - 1].append(y_value)
                X_list[annual_index - 1].append(X_values)
                trainingdate_list.append(index)

        self.trainingdates = trainingdate_list

        for i, item in enumerate(y_list):
            x_set = self._X_scaler[i].fit_transform(array(X_list[i]))
            y_set = self._y_scaler[i].fit_transform(array(y_list[i]).reshape(-1,1))

            if len(y_set) > 0:
                try:
                    #from pyramid.arima import ARIMA
                    #fit = ARIMA(order=(1, 1, 1), seasonal_order=(0, 1, 1, 36)).fit(y=y_set.ravel())
                    self._model[i].fit(x_set, y_set.ravel())
                except Exception as err:
                    print(
                        "An error occured while training the model for annual index %s. Please check the training data." % (
                            i + 1))
                    raise err
            else:
                raise self.InsufficientData(
                    "There is not enough data to train the model for the period with annualindex %s" % (i + 1))

    def predict(self, targetdate, X):
        """Returns the predicted value for y at targetdate

            Uses the trained model to predict y for the period that targetdate is member of.

            Args:
                targetdate: A datetime.date object that is member of the period for which y should be forecasted.
                X: A list of FixedIndexTimeseriesobjects of the type and order of the Forecaster.X_type attribute

            Returns:
                a float of the predicted value.

            Raises:
                ValueError: if X does not fit the type of X that the Forecaster instance was initialised with
                InsufficientData: is raised when the dataset in X does not contain enough data to predict y.
                ModelError: is raised when the model have not yet been trained but a forecast is requested.
            """
        type = [x.mode for x in X]
        if not type == self._X_type:
            raise ValueError(
                "The input dataset X must be a list of FixedIndexTimeseries objects with type and length %s" % self._X_type)

        featuredates = self._aggregate_featuredates(targetdate)
        if self._multimodel:
            annual_index = self._y.convert_to_annual_index(targetdate)
        else:
            annual_index = 1
        X_values = self._aggregate_features(featuredates, X)
        if not self.trainingdates:
            raise self.ModelError(
                "There is no trained model to be used for a prediciton. Call class method .train() first.")
        elif isnan(X_values).any():
            raise self.InsufficientData("The data in X is insufficient to predict y for %s" % targetdate)
        else:
            x_set = self._X_scaler[annual_index - 1].transform(X_values.reshape(1, -1))
            prediction = self._model[annual_index - 1].predict(x_set)
            invtrans_prediction = self._y_scaler[annual_index - 1].inverse_transform(prediction.reshape(-1,1))
            return invtrans_prediction+self._seasonal[self._y.convert_to_annual_index(targetdate)-1]

    def _predict_on_trainingset(self):
        if not self.trainingdates:
            self.train()

        target = pandas.Series(index=self.trainingdates)
        for date in target.index:
            target[date] = self.predict(date, self._X)
        predicted_ts = FixedIndexTimeseries(target.sort_index(), mode=self._y.mode)
        targeted_ts = self._y
        return Evaluator(targeted_ts, predicted_ts)

    def cross_validate(self, k_fold='auto'):
        # UNDER DEVELOPMENT
        # TODO Need to incoorporate self.trainingdates, otherwise min k_fold value is overestimated
        self.indicate_progress(0)

        y = []

        # Aggregate data into groups for each annualindex
        if self._multimodel:
            for i in range(0, self._maxindex):
                y.append(self._y.data_by_index(i + 1))
        else:
            y.append(self._y.timeseries)

        # Check if each group has enough samples for the value of k_fold
        groupsize = map(len,y)
        if k_fold=='auto':
            k_fold=min(groupsize,10)
            if k_fold==1:
                raise self.InsufficientData(
                    "There are not enough samples for cross validation. Please provide a large dataset"
                )
        elif k_fold==1 or not isinstance(k_fold,int):
            raise ValueError(
                "The value of k_fold must be 2 or larger."
            )
        elif not all(map(lambda x: x>=k_fold,groupsize)):
            raise self.InsufficientData(
                "There are not enough samples for cross validation with k_fold=%s. Please choose a lower value." %k_fold
            )

        # Split each group with KFold into training and test sets (mixes annual index again, but with equal split )
        maxsteps = len(y)+k_fold*10+1
        t=1
        self.indicate_progress(float(t)/maxsteps*100)
        t+1
        train = [pandas.Series()] * k_fold
        test = [pandas.Series()] * k_fold
        kf = KFold(n_splits=k_fold, shuffle=False)
        for i, values in enumerate(y):
            self.indicate_progress(float(t) / maxsteps * 100)
            t=t + 1
            k = 0
            if len(y[i]) > 1:
                for train_index, test_index in kf.split(y[i]):
                    train[k] = train[k].append(y[i][train_index])
                    test[k] = test[k].append(y[i][test_index])
                    k += 1

        # For each KFold: train a Forecaster Object and predict the train set.
        predictions = []
        dates = []
        for i, trainingset in enumerate(train):
            self.indicate_progress(float(t) / maxsteps * 100)
            t = t + 10
            fc = Forecaster(clone(self._model[0]), FixedIndexTimeseries(trainingset, mode=self._y.mode), self._X,
                            self._laglength, self._lag, self._multimodel, self._decompose)
            fc.train()
            for target in test[i].iteritems():
                try:
                    predictions.append(fc.predict(target[0], self._X)[0,0])
                    dates.append(target[0])
                except:
                    pass
        predicted_ts = FixedIndexTimeseries(pandas.Series(data=predictions, index=dates).sort_index(),mode=self._y.mode)
        targeted_ts = self._y
        return Evaluator(targeted_ts, predicted_ts)

    def indicate_progress(self,p):
        print("progress is %s%%" %(p))

    class InsufficientData(Exception):
        pass

    class ModelError(Exception):
        pass