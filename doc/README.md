﻿
# hydromet forecasting

## Introduction

The library is designed to automise and enhance the forecasting method, that the hydrometeorological agency in Kyrgyzstan produces for pentadal (5-day), decadal (10-day), monthly and seasonal timeseries of their river basins. Originally, these forecasts are produced manually, using MS Excel and expert knowledge. The module has been developed with the goal, to digitize the manual procedure and give space for some more experiments with additional data sources like snow timeseries and machine learning methods.
The library has two distinguished methods for normal, continuous forecasts like monthly and another method (grid-search) for seasonal forecasting. The latter was implemented on the basis of this research paper by Heiko Apel et. al: https://www.hydrol-earth-syst-sci.net/22/2225/2018/

## Overview
The library is split into three parts: Timeseries, Forecasting and Evaluating
#### Timeseries
 Unfortunately, the pandas library does not support timeseries with decadal or pentadal frequency. For this reason, a new class was designed, that wraps around pandas to handle such frequencies.
 
##### FixedIndexTimeseries
FixedIndex means, that each year has the same number of periods and that every period takes the same position in every year, e.g. monthes or semi-monthes etc. It does not work for timeseries with periods, that strictly consist of the same number of days like "weeks" and as such, might overlap New Year.
In this class, the attribute "timeseries" contains the pandas dataframe. Here, every datapoint is assigned a date, which is the first day of the timeperiod that it describes. E.g. in monthly timeseries datetime.date(2011,6,1) is the timestamp of the datapoint for June 2011.

A timeseries can be read by using the child class FixedIndexTimeseriesCSV. When initialising, a mode must be given and can be either:

* 'p' for pentadal data
* 'd' for decadal data
* 'm' for monthly data 
* 'dl' for daily data (day 366 is ignored for simplicity)
* 'xx-yy' for seasonal data, whereby xx is the first month and yy is the second month as two digit integer: e.g. '04-09' for April to and including September

The CSV file must be formatted in the following way:

* Rows contain the data of 1 year.
* The first cell in each row contains the year e.g. 2018 of that row. 
* The length of the rows corresponds to the number of periods, e.g. monthly 12+1(yearvalue)
* Empty cells and strings are read as NaN


~~~~ 
2010,21.6,21.4,23.1,31.8,20.6,45.3,25.2,11.3,23.9,29.6,28.1,27
2011,23.3,22.7,24.9,26.6,18,31.7,15.1,,20.8,26.8,28.9,26.7
2012,23.8,,22.1,15.6,2.7,10.4,6.4,3.3,11.8,12.4,19.4,21.6
~~~~

The class offers several method to manipulate the timeseries, extract information or handle the frequency mode. 

Load a csv:
~~~~
precipitation=FixedIndexTimeseriesCSV("example_data/monthly/P.csv",mode="m")
~~~~

#### Forecasting

##### Regression Model (sklearn Estimator)

This class helps to initialise a sklearn estimator from a selection. At the moment, only linear regression, decision tree regression and the lasso regression estimators are enabled. It is possible to add other estimator classes, but for the use case here the mentioned estimators are sufficient.

An estimator (here called model) is initialised in the following way:

~~~~
print(RegressionModel.SupportedModels.list_models())

# Initialise a decision tree model class
reg_model = RegressionModel.build_regression_model(RegressionModel.SupportedModels(3))

# Print default model parameters:
print("Default parameters: %s" %reg_model.default_parameters)

# Print possible parameter choices:
print("Possible parameters or range: %s" %reg_model.selectable_parameters)

# Set parameter and configure the regression model from the model class
model=reg_model.configure({'n_estimators':20})  
~~~~


##### Forecaster
This is the class for general forecasts resp. everything with lower frequency than seasonal timeseries. It is initialised in minimum with an Regression Model Instance (see above), a target timeseries y (FixedIndexTimeseries Instance, see above), a list of feature timeseries X and a list of laglengths that correspond to the features. The laglength defines how many timelags of a feature are included in the forecast, e.g. for a monthly timeseries a value of 3 means the last 3 month. Additional parameters let you specify more details.

A basic initialisation is:
~~~~
FC_obj = Forecaster(model=model,y=discharge,X=[discharge,temperature,precipitation],laglength=[3,3,3])
~~~~

In order to train this model, the method train_and_evaluate() is called. It returns an Evaluator (see below) instance, with which one can write an html report of the model performance. The model performance is assessed by a k-fold cross validation on is done using all available data. Depending on the amount of available data and complexity of the model, this process might take a while. The train_and_evaluate() function takes the argument feedback_function, which is triggered every step, e.g. can report on the current state of the computation. A valid feedback_function must take the argument i and i_max, whereby i is the current step and i_max is the maximal, final step.
~~~~
def print_percentage(i, i_max):
    print(int(100*i/i_max)
    
PA_obj = FC_obj.train_and_evaluate(feedback_function=print_percentage)
PA_obj.write_html("assessment_report.html")
~~~~

The model can also be trained without evaluating it by calling train().  (Remark: This function could be used in a further step to retrain the model as soons as there are new data, but no new evaluation report is required. For this another function will be implemented in the next version, allowing the update of the target and feature data. TODO)

Finally, in order to make a prediction with the trained model. the function predict() is called.

~~~~
prediction = FC_obj.predict(targetdate=datetime.date(2011,6,2),X=[discharge,temperature,precipitation])
~~~~
 Two arguments need to be given:
 
* A targetdate as datetime.date object: The targetdate defines the targetperiod. It points to a date which is within that targetperiod, but it does not matter if it is its first or last or any other date within the period. E.g. datetime.date(2011,6,1), datetime.date(2011,6,12), datetime.date(2011,6,30) all point to the timeperiod of June for a target timeseries of monthly frequeny resp. mode='m'.
* X, a list of featuredata in the same format as it was when initialising the Forecaster instance. The FixedIndexTimeseries given here usually contain newer data as when initialising the Forecaster instance. They do not need to contain all data available, but might only contain the data that is required for that specific forecasting setup (laglength, etc.) and targetdate. All additional data is ignored. If not all required data is given, the function will raise and InsufficientData Exception.






