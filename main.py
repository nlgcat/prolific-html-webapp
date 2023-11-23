# This is the webapp for hosting Prolific surveys for the Edinburgh Napier University lab within the reprohum project.
# The data is in csv format, containing the data from the survey. File name should be data.csv
# The user interface is the interface.html file, which is a template for the survey.
# Each interface has the following structure ${outputb1} where inside the brackets is the name of the variable.
# There can be multiple variables - which should be defined in the python code to match the variable names in the csv file.
import json
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, render_template_string
import csv
import pandas as pd
import re
import uuid as uuid_lib
import os

# Load the data from the csv file into a pandas dataframe
df = pd.read_csv('data.csv')

# Create a list of the column names in the csv file
column_names = df.columns.values.tolist()

#print(column_names)

# Create a list of dictionaries, where each dictionary is a row in the csv file

app = Flask(__name__)

def preprocess_html(html_content, df, task_id=-1):

    for column_name in column_names:
        html_content = html_content.replace("${"+column_name+"}", str(df[column_name].values[0]))

    html_content = html_content.replace("${task_id}", str(task_id))

    return html_content


@app.route('/', methods=['GET', 'POST'])
def index():

    if request.method == 'POST':
        # Print JSON from POST request
        print(request.json)

        # Save JSON to file with task_id as the folder and uuid as the filename
        task_id = request.json['task_id']
        folder_path = os.path.join('data', str(task_id))
        os.makedirs(folder_path, exist_ok=True)  # Create folder if it doesn't exist

        uuid = str(uuid_lib.uuid4())
        file_path = os.path.join(folder_path, f"{uuid}.json")

        with open(file_path, 'w') as outfile:
            json.dump(request.json, outfile)

        return "OK", 200
    else:
        return "Nothing Here.", 200


@app.route('/row/<int:row_id>', methods=['GET', 'POST'])
def row(row_id):

    # Read the HTML template file
    with open('templates/interface.html', 'r') as html_file:
        html_content = html_file.read()

    # Preprocess the HTML content
    processed_html = preprocess_html(html_content, df.iloc[[row_id]], row_id)

    return render_template_string(processed_html)


tasks = {i: {"count": 0, "participants": [], "assigned_count": 0} for i in range(len(df))}

# Study route, get PROLIFIC_PID, STUDY_ID and SESSION_ID from URL parameters
@app.route('/study/')
def study():

    # Get PROLIFIC_PID, STUDY_ID and SESSION_ID from URL parameters
    prolific_pid = request.args.get('PROLIFIC_PID')
    study_id = request.args.get('STUDY_ID')
    session_id = request.args.get('SESSION_ID')

    # Find a task that has not been completed

    # Generate the task page with prolific_pid, study_id and session_id as hidden fields

    # Return the task page

    # Need to remember that each task (row) needs to be completed exactly three times by different participants
    # So we need to keep track of how many times each task has been completed as well as which participants have completed each task
    # We also need to keep track of how many times a task has been completed. If it has been completed three times, then we need to move on to the next task.

    # We could also automatically run attention checks on the data to check for bots and other issues. If the check fails, we can save JSON into failed folder.
    # At that point we won't rerun the task. We will wait until the rest of the tasks have been completed and then rerun the failed tasks together.

    # When we get a submission, we should also be storing the prolific_pid, study_id and session_id in the JSON file.

    # Read the HTML template file
    with open('templates/interface.html', 'r') as html_file:
        html_content = html_file.read()

    # Find a task that has been assigned less than three times
    for task_id, task_info in tasks.items():
        if task_info["assigned_count"] < 3:
            # Assign the task to the user
            tasks[task_id]["assigned_count"] += 1
            break
    else:
        return "All tasks have been assigned three times.", 200

    html_content = preprocess_html(html_content, df.iloc[[task_id]], task_id)
    html_content += f'<input type="hidden" name="prolific_pid" value="{prolific_pid}">'
    html_content += f'<input type="hidden" name="study_id" value="{study_id}">'
    html_content += f'<input type="hidden" name="session_id" value="{session_id}">'
    return render_template_string(html_content)
    

    #return "no", 400 # TODO: Remove this line

@app.route('/tasksallocated')
def aloced():
    return tasks

if __name__ == '__main__':
    app.run(debug=True)

