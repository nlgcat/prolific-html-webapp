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


#TODO: REFRESH SHOULD NOT ALLOCATE NEW TASK - IT SHOULD JUST REFRESH THE CURRENT TASK and not increment the counter
#TODO: TASK ONCE COMPLETED SHOULD NOT BE ABLE TO BE MARKED AS ABANDONED
#TODO: SAVE TO FILE RATHER THAN JSON - WE DONT REALLY WANT IT SAVED IN MEMORY - WE WANT TO BE ABLE TO RESTART THE SERVER AND NOT LOSE DATA

MAX_TIME = 3600  # Maximum time in seconds that a task can be assigned to a participant before it is abandoned - 1 hour = 3600 seconds
                 # Should probably note the 1hr limit on the interface/instructions. And could allow JS to flag up a warning if the time is getting close to 1hr. - Future work.

# Load the data from the csv file into a pandas dataframe
df = pd.read_csv('data.csv')
# Create a list of the column names in the csv file
column_names = df.columns.values.tolist()

# Create a dictionary of tasks, where each task is a row in the csv file
# This should probably be saved to a file rather than in memory, so that we can restart the server and not lose data.
tasks = {i: {"completed_count": 0, "participants": [], "assigned_times": []} for i in range(len(df))}

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

        # Update the completed_count for the task
        if task_id in tasks:
            tasks[task_id]["completed_count"] += 1
            # Ensure that completed_count does not exceed 3
            #tasks[task_id]["completed_count"] = min(tasks[task_id]["completed_count"], 3) # hiding this as it should never be more than 3, and we want to know if that happens.

        return "OK", 200
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
    study_id = request.args.get('STUDY_ID')
    session_id = request.args.get('SESSION_ID')

    # Read the HTML template file
    with open('templates/interface.html', 'r') as html_file:
        html_content = html_file.read()

    # Find a task that has been assigned less than three times
    for task_id, task_info in tasks.items():
        if len(task_info["participants"]) < 3:
            # Task found, assign the task to the user
            tasks[task_id]["participants"].append(prolific_pid)
            tasks[task_id]["assigned_times"].append(datetime.now())
            break
    else:
        return "All tasks have been assigned three times.", 200

    html_content = preprocess_html(html_content, df.iloc[[task_id]], task_id)
    html_content += f'<input type="hidden" name="prolific_pid" value="{prolific_pid}">'
    html_content += f'<input type="hidden" name="study_id" value="{study_id}">'
    html_content += f'<input type="hidden" name="session_id" value="{session_id}">'
    return render_template_string(html_content)
    

    #return "no", 400 # TODO: Remove this line

# This route is used for testing - it will return the tasks dictionary showing the number of participants assigned to each task
@app.route('/tasksallocated')
def aloced():
    return tasks


# Check for tasks that have been assigned for more than 1 hour and then open them up again for participants to complete. Code at bottom of file will make this run every hour.
# The route is set up for testing to manually check for abandoned tasks. It will return a list of abandoned tasks that have been opened up again.
@app.route('/abdn')
def check_abandonment():
    print("Checking for abandoned tasks...")
    abdnd = []
    current_time = datetime.now()

    for task_id, task_info in list(tasks.items()):
        # Iterate backward through the assigned_times
        for i in range(len(task_info['assigned_times']) - 1, -1, -1):
            assigned_time = task_info['assigned_times'][i]
            time_diff = (current_time - assigned_time).total_seconds()

            # If the time difference is more than 1 hour, remove the participant and time
            if time_diff > 3600:
                print(f"Removing participant {task_info['participants'][i]} from task {task_id}")
                task_info['assigned_times'].pop(i)
                task_info['participants'].pop(i)
                abdnd.append(task_id)

    return "Abandoned tasks: " + str(abdnd), 200


# CLI Entry Point (for testing) - python main.py

if __name__ == '__main__':
    app.run(debug=True)


# Scheduler

# Run the check_abandonment function every hour
from apscheduler.schedulers.background import BackgroundScheduler
scheduler = BackgroundScheduler()
scheduler.add_job(func=check_abandonment, trigger="interval", seconds=MAX_TIME)
scheduler.start()
