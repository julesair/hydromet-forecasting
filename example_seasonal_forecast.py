from hydromet_forecasting.forecasting import RegressionModel, SeasonalForecaster
from hydromet_forecasting.timeseries import FixedIndexTimeseriesCSV
import datetime


# ---------------- SETUP OF A REGRESSION MODEL ----------------

# Get a dict of available regression methods
print(RegressionModel.SupportedModels.list_models())

# Initialise a regression model class
reg_model = RegressionModel.build_regression_model(RegressionModel.SupportedModels(1))

# Print default model parameters:
print("Default parameters: %s" %reg_model.default_parameters)

# Print possible parameter choices:
print("Possible parameters or range: %s" %reg_model.selectable_parameters)

# Set parameter and configure the regression model from the model class
model=reg_model.configure()  #{'n_estimators':20}

# ---------------- LOADING TIMESERIES DATA FROM A FILE & DOWNSAMPLING ----------------
# modes: "m","d","p","dl" --> monthly, decadal, pentadal, daily

Talas_Q=FixedIndexTimeseriesCSV("example_data/monthly/Talas_Kluchevka/Q.csv",mode="m")
Talas_P=FixedIndexTimeseriesCSV("example_data/monthly/Talas_Kluchevka/PREC_ERA.csv",mode="m")
Talas_T=FixedIndexTimeseriesCSV("example_data/monthly/Talas_Kluchevka/TEMP_ERA.csv",mode="m")
Talas_S = FixedIndexTimeseriesCSV("example_data/daily/Talas_Kluchevka/SNOW.csv",mode="dl")
Talas_S = Talas_S.downsample(mode='m')

# ---------------- INITIALISING THE SEASONAL FORECASTING OBJECT ----------------

# This class does a grid search over multiple feature-timewindow combinations and output the best regression models.
# '04-09': season from April to September
# forecast_month=4 : forecast is done on 1st April
# earliest_month=2 : data are used from February until 1st of April
# max_features=2 : limits the number of features per model to a maximum of 2
# n_model=4 : The 4 best models are stored and used for forecasting
# For demonstration purposes, the arguments here are optimized for a quick grid search. The resulting model performance is thus rather low.
FC_obj = SeasonalForecaster(model=model, target=Talas_Q.downsample('04-09'), Qm=Talas_Q, Pm=Talas_P, Sm=Talas_S, Tm=Talas_T, forecast_month=4, earliest_month=3, max_features=2, n_model=20)

# ---------------- STARTING THE GRIDSEARCH & OUTPUT A PERFORMANCE ASSESSMENT ----------------
def print_progress(i, i_max):  print(str(i) + ' of ' + str(int(i_max)))
PA_obj = FC_obj.train_and_evaluate(feedback_function=print_progress)
PA_obj.write_html("assessment_report.html")

# ---------------- FORECAST ----------------
# datetime.date(2014,4,1) refers to the target timewindow from April to September. datetime.date(2014,9,30) would give the same result.
prediction=FC_obj.predict(targetdate=datetime.date(2014,4,1),Qm=Talas_Q,Pm=Talas_P,Sm=Talas_S,Tm=Talas_T)
print(prediction)
