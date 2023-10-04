# This is the webapp for hosting Prolific surveys for the Edinburgh Napier University lab within the reprohum project.
# The data is in csv format, containing the data from the survey. File name should be data.csv
# The user interface is the interface.html file, which is a template for the survey.
# Each interface has the following structure ${outputb1} where inside the brackets is the name of the variable.
# There can be multiple variables - which should be defined in the python code to match the variable names in the csv file.

from flask import Flask, render_template, request, redirect, url_for, render_template_string
import csv
import pandas as pd
from markupsafe import Markup, escape
import re

# Load the data from the csv file into a pandas dataframe
df = pd.read_csv('data.csv')

# Create a list of the column names in the csv file
column_names = df.columns.values.tolist()

print(column_names)

# Create a list of dictionaries, where each dictionary is a row in the csv file

app = Flask(__name__)

def preprocess_html(html_content, df):

    for column_name in column_names:
        html_content = html_content.replace("${"+column_name+"}", str(df[column_name].values[0]))

    return html_content


@app.route('/')
def index():
    return "Nothing Here.", 200


@app.route('/row/<int:row_id>')
def row(row_id):
    # Read the HTML template file
    with open('templates/interface.html', 'r') as html_file:
        html_content = html_file.read()

    # Preprocess the HTML content
    processed_html = preprocess_html(html_content, df.iloc[[row_id]])

    return render_template_string(processed_html)


if __name__ == '__main__':
    app.run(debug=True)

