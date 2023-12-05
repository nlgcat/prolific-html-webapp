
# Flask Server for Prolific Tasks

> This code is in development and has not been fully tested. Please use with caution.

## Required files:
- data.csv - this is the datafile containing the rows of data for each task
- templates/interface.html - this is the interface for the HIT
- database.db - This file will be created once you run the CreateDatabase.py script with the correct number of tasks (see below). 

## Setup:

1. First, CreateDatabase.py should be run first to create the database and tables. You must first update the COMPLETIONS_PER_TASK variable to the number of completions you want per task. This is the number of times each task will be completed by a worker. The default is 3.
2. Ensure all required files (see above) have been added for the new task.
3. Update main.py's MAX_TIME variable to the maximum time you want the task to run for. The default is 60 minutes (3600 seconds).
4. Update your interface.html file as required (see "Task Interface Changes" below).
5. When ready, you will need to deploy the flask app to a server.


## Task Interface Changes

1. We must add a submit button that will collate the worker entered data and send it as JSON POST request to the server running the flask app.
   This will require a new JS function to be added to the HTML file. **Make sure to include the task_id, prolific_pid, and session_id in the JSON data.**
   Example: 
    ```JS 
   var task_id = document.getElementById("task_id").innerHTML;
   var prolific_pid = document.getElementById("prolific_pid").value;
   var session_id = document.getElementById("session_id").value;
   ```

2. We must also add a hidden field that will contain the task id. This can then be used to identify the task in the database for analysis.
    Example: `<p hidden class="hidden">This is HiT: </p><p hidden class="hidden" id="task_id">${task_id}</p>`
    Note: this is not required for SessionID or ProlificID - as the preprocess function will add these to the data.
  3. Optional: Depending on your task, you may wish to include an alert for warning the worker when they have run out of time. 
    
    ```JS
     function startFailedCountdown() {
        var minutes = 60; //var minutes = 60;
        var seconds = 0;
        var totalSeconds = minutes * 60 + seconds;

        var interval = setInterval(function() {
            seconds--;
            if (seconds < 0) {
                minutes--;
                seconds = 59;
            }

            if (minutes < 0) {

                // Disable the submit button
                document.getElementById("submit-button").disabled = true;
                document.getElementById("submit-button").innerHTML = "You cannot submit this HIT anymore.";
                document.getElementById("submit-button").classList.add("is-danger")

                clearInterval(interval);

                alert("The allocated time for this task has passed. Your answers will not be used and you will not be paid.");

                // Redirect the worker to the Prolific app: https://app.prolific.com/
                window.location.href = "https://app.prolific.co/";

            }
        }, 1000);
    }

    startFailedCountdown();
   ```
   
You could also repeat this code to alert the worker when they have 10 minutes left, etc.
