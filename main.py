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

import DataManager as dm

MAX_TIME = 3600  # Maximum time in seconds that a task can be assigned to a participant before it is abandoned - 1 hour = 3600 seconds
                 # Should probably note the 1hr limit on the interface/instructions. And could allow JS to flag up a warning if the time is getting close to 1hr. - Future work.

# Load the data from the csv file into a pandas dataframe
df = pd.read_csv('data.csv')
# Create a list of the column names in the csv file
column_names = df.columns.values.tolist()

# Create a dictionary of tasks, where each task is a row in the csv file
# This should probably be saved to a file rather than in memory, so that we can restart the server and not lose data.
#tasks = {i: {"completed_count": 0, "participants": [], "assigned_times": []} for i in range(len(df))}

app = Flask(__name__) # Create the flask app

# MTurk template replacement tokens is different to Jinja2, so we just do it manually here.
def preprocess_html(html_content, df, task_id=-1):

    for column_name in column_names:
        html_content = html_content.replace("${"+column_name+"}", str(df[column_name].values[0]))

    html_content = html_content.replace("${task_id}", str(task_id))

    return html_content


# Routes

# This is the index route, which will just say nothing here. If it gets a POST request, it will save the HIT response JSON to a file.
# NOTE: The HTML interfaces should be updated with a button that compiles the answers as a JSON object and POSTS to this app.
# TODO: Validate submission is JSON and has required fields (task_id, prolific_pid, etc)
# TODO: Make sure database isnt locked after POST request
@app.route('/', methods=['GET', 'POST'])
def index():

    if request.method == 'POST':
        # Print JSON from POST request
        print(request.json)

        # Save JSON to file with task_id as the folder and uuid as the filename
        task_id = request.json['task_id']
        prolific_pid = request.json['prolific_pid']
        folder_path = os.path.join('data', str(task_id))
        os.makedirs(folder_path, exist_ok=True)  # Create folder if it doesn't exist

        file_path = os.path.join(folder_path, f"{task_id}.json")

        with open(file_path, 'w') as outfile:
            json.dump(request.json, outfile)

        # Complete the task
        print(task_id, request.json, prolific_pid)
        dm.complete_task(task_id, str(request.json), prolific_pid)
        return {"result":"OK"}, 200
    else:
        return "Nothing Here.", 200

# This route is used for testing the interface on specific rows of the csv file
@app.route('/row/<int:row_id>', methods=['GET', 'POST'])
def row(row_id):
    # Read the HTML template file
    with open('templates/interface.html', 'r') as html_file:
        html_content = html_file.read()
    # Preprocess the HTML content
    processed_html = preprocess_html(html_content, df.iloc[[row_id]], row_id)
    return render_template_string(processed_html)


# Study route, get PROLIFIC_PID, STUDY_ID and SESSION_ID from URL parameters
# This route will assign a task to a participant and return the HTML interface for that task
# It *should* be updated to allow the participant to continue where they left off if they refresh the page - this will be implemented using the PROLIFIC_PID searching on pending tasks.
@app.route('/study/')
def study():

    # Get PROLIFIC_PID, STUDY_ID and SESSION_ID from URL parameters
    prolific_pid = request.args.get('PROLIFIC_PID')
    session_id = request.args.get('SESSION_ID')

    # Read the HTML template file
    with open('templates/interface.html', 'r') as html_file:
        html_content = html_file.read()

    # Allocate task or find already allocated task
    if prolific_pid is None or session_id is None:
        return "PROLIFIC_PID and SESSION_ID are required parameters.", 400
    else:
        task_id, task_number = dm.allocate_task(prolific_pid, session_id)

    # If there is a database error, return the error message and status code
    if task_id == "Database Error - Please try again, if the problem persists contact us." and task_number == -1:
        return task_id, 500


    # If no task is available, return a message
    if task_id is None:
        return "No tasks available", 400

    html_content = preprocess_html(html_content, df.iloc[[task_number]], task_id) # Params: html_content, df, task_id=-1
    html_content += f'<input type="hidden" id="prolific_pid" value="{prolific_pid}">'
    html_content += f'<input type="hidden" id="session_id" value="{session_id}">'
    return render_template_string(html_content)


# This route is used for testing - it will return the tasks dictionary showing the number of participants assigned to each task
@app.route('/tasksallocated')
def aloced():

    tasks = dm.get_all_tasks()

    return tasks

# Show a specific task_id's result in the database
@app.route('/results/<task_id>')
def results(task_id):
    result = dm.get_specific_result(str(task_id))
    if result is None:
        return "No result found for task_id: " + str(task_id), 400
    return str(result)


# Check for tasks that have been assigned for more than 1 hour and then open them up again for participants to complete. Code at bottom of file will make this run every hour.
# The route is set up for testing to manually check for abandoned tasks. It will return a list of abandoned tasks that have been opened up again.
@app.route('/abdn')
def check_abandonment():
    print("Checking for abandoned tasks...")
    dm.expire_tasks(MAX_TIME)

    tasks = dm.get_all_tasks()

    return tasks, 200

# Scheduler

# Run the check_abandonment function every hour - this has to be before the app.run() call
from apscheduler.schedulers.background import BackgroundScheduler
scheduler = BackgroundScheduler()
scheduler.add_job(func=check_abandonment, trigger="interval", seconds=MAX_TIME)
scheduler.start()


# CLI Entry Point (for testing) - python main.py

if __name__ == '__main__':
    app.run(debug=True)

