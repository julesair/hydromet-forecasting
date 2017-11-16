import datetime

import enum
import pandas
from numpy import nan, array, isnan, full
from sklearn.base import clone
from sklearn.model_selection import KFold
from numbers import Number


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
        selectable_parameters: dictionary of possible parameters as parameter_type and a [min,max] range when numeric, or
        a list of choices when boolean or string.
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
            for key in parameters:
                if not key in self.default_parameters.keys():
                    raise ValueError("The given parameter name %s is invalid" %key)
                elif isinstance(self.default_parameters[key],Number) and not isinstance(self.default_parameters[key], bool):
                    range=self.selectable_parameters[key]
                    if not range[0]<=parameters[key]<=range[1]:
                        raise ValueError("The given value for %s is outside the valid range %s." %(key,range))
                else:
                    if not parameters[key] in self.selectable_parameters[key]:
                        raise ValueError("The given value for %s must be one of these %s." %(key, self.selectable_parameters[key]))

            return self.model_class(**parameters)

    class SupportedModels(enum.Enum):
        """Enum class for available models:

            list_models(): Returns: dictionary of available models as name,value pairs """

        linear_regression = 1
        extra_forests = 2

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

        if model == cls.SupportedModels.linear_regression:
            from sklearn import linear_model
            return cls(linear_model.LinearRegression,
                       {'fit_intercept': [True, False]},
                       {'fit_intercept': True})
        elif model == cls.SupportedModels.extra_forests:
            from sklearn import ensemble
            return cls(ensemble.ExtraTreesRegressor,
                       {'n_estimators': [10, 1000]},
                       {'n_estimators': 50})


class Forecaster(object):
    """Forecasting class for timeseries that can be handled/read by FixedIndexDatetil.

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

    def __init__(self, model, y, X, laglength, lag=0, multimodel=True):
        """Initialising the Forecaster Object

            Args:
                model: A model object that knows the method fit() and predict() for
                        a targetvector y and a feature array X
                y: A FixedIndexTimeseries Instance that is the target data
                X: A list of FixedIndexTimeseries Instances that represent the feature data
                laglength: A list of integers that define the number of past periods that are used from the feature set.
                        Must have the same length as X
                lag: (int): when positive: the difference in days between forecasting date and the first day of the forecasted period
                            when negative: the difference in days between forecasting date and the first day of the period preceding the forecasted period
                            Example:
                                forecasted, decadal period is: 11.10-20.10,
                                lag=0, laglength=1: The forecast is done on 11.10. The period 1.10 to 10.10 is used as feature.
                                lag=4, laglength=2: The forecast is done on 7.10. The periods 21.9-30.9 and 11.9-20.9 is used as feature
                                lag=-3, laglength=1: The forecast is done on 4.10. The period 21.9 to 30.9  is used as feature.
                multimode: boolean. If true, a individual model is trained for each period of the year. Makes sense when the
                            timeseries have annual periodicity in order to differentiate seasonality.

            Returns:
                A Forecaster object with the methods train and predict

            Raises:
                ValueError: When the list "laglength" is of different length than the list X.
            """

        self._model = model
        self._multimodel = multimodel

        self._y = y
        self._y.timeseries.columns = ["target"]

        if type(X) is not list:
            self._X = [X]
        else:
            self._X = X

        self._X_type = [x.mode for x in self._X]
        self._lag = lag

        if type(laglength) is not list:
            self._laglength = [laglength]
        else:
            self._laglength = laglength

        if not len(self._laglength) == len(X):
            raise ValueError("The arguments laglength and X must be lists of the same length")

        if not self._multimodel:
            self._maxindex = 1
            self._model = [self._model]
        else:
            self._maxindex = self._y.maxindex
            self._model = [clone(self._model) for i in range(self._maxindex)]

        assert len(self._X) > 0, "predictor dataset must contain at least one feature"
        assert len(self._laglength) == len(self._X), "The list laglength must contain as many elements as X"

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
                X_values[k:k + self._laglength[i]] = x.timeseries[featuredates[i]].values
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

        for i, item in enumerate(y_list):
            x_set = array(X_list[i])
            y_set = array(y_list[i])
            if len(y_set) > 0:
                try:
                    self._model[i].fit(x_set, y_set)
                except Exception as err:
                    print(
                        "An error occured while training the model for annual index %s. Please check the training data." % (
                            i + 1))
                    raise err
            else:
                raise self.InsufficientData(
                    "There is not enough data to train the model for the period with annualindex %s" % (i + 1))

        self.trainingdates = trainingdate_list

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
            return self._model[annual_index - 1].predict(X_values.reshape(1, -1))[0]

    def _predict_on_trainingset(self):
        target = pandas.Series(index=self.trainingdates)
        for date in target.index:
            target[date] = self.predict(date, self._X)
        return FixedIndexTimeseries(target, mode=self._y)

    def _cross_validate(self, k_fold=5):
        # UNDER DEVELOPMENT
        y = []

        # Aggregate data into groups for each annualindex
        if self._multimodel:
            for i in range(0, self._maxindex):
                y.append(self._y.data_by_index(i + 1))
        else:
            y.append(self._y.timeseries)

        # Split each group with KFold into training and test sets (mixes annual index again, but with equal split )
        train = [pandas.Series()] * 5
        test = [pandas.Series()] * 5
        kf = KFold(n_splits=5)
        for i, values in enumerate(y):
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
            fc = Forecaster(self._model[0], FixedIndexTimeseries(trainingset, mode=self._y.mode), self._X,
                            self._laglength, self._lag, self._multimodel)
            fc.train()
            for target in test[i].iteritems():
                try:
                    predictions.append(fc.predict(target[0], self._X))
                    dates.append(target[0])
                    print(fc.predict(target[0], self._X))
                except:
                    pass
        predicted_ts = FixedIndexTimeseries(pandas.Series(data=predictions, index=dates).sort_index(),
                                            mode=self._y.mode)
        targeted_ts = FixedIndexTimeseries(self._y.timeseries[dates])
        return Evaluator(targeted_ts, predicted_ts)

    def trainingdata_count(self, dim=0):
        year_min = self.trainingdates[0].year
        year_max = self.trainingdates[-1].year
        mat = pandas.DataFrame(full((self._y.maxindex, year_max - year_min + 1), False, dtype=bool),
                               columns=range(year_min, year_max + 1))
        mat.index = range(1, self._y.maxindex + 1)

        for date in self.trainingdates:
            mat.loc[self._y.convert_to_annual_index(date), date.year] = True

        if dim == 0:
            return mat.sum().sum()
        elif dim == 1:
            return mat.sum(axis=1)
        elif dim == 2:
            return mat

    class InsufficientData(Exception):
        pass

    class ModelError(Exception):
        pass


class Evaluator(object):
    """UNDER DEVELOPMENT: This class will contain all information and methods for assessing model performance

    It will have a method write_pdf(filename), that generates the assessment report and writes it to "filename".
    When no filename is given, the pdf is stored in a temporary folder.
    Returns: the pathname where the pdf is stored.
    """

    def __init__(self, y, forecast):
        self.y = y
        self.forecast = forecast

    def computeP(self):
        P = []
        allowed_error = map(lambda x: x * 0.674, self.y.stdev_s())
        years = range(min(self.y.timeseries.index).year, max(self.y.timeseries.index).year + 1)
        for index in range(0, self.y.maxindex):
            dates = map(self.y.firstday_of_period, years, len(years) * [index + 1])
            try:
                error = abs(self.forecast.timeseries[dates] - self.y.timeseries[dates])
                error.dropna()
                good = sum(error <= allowed_error[index])
                P.append(float(good) / len(error.dropna()))
            except:
                P.append(nan)
        return P

    def write_pdf(self, filename):
        import matplotlib.pyplot as plt
        P = self.computeP()

        f = plt.figure()
        plt.plot(P)
        f.savefig(filename, bbox_inches='tight')
        return filename
