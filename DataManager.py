import sqlite3
from datetime import datetime

# TODO: All functions should be using with create_connection() as conn: and conn.commit() and conn.close() to ensure the connection is closed properly
# TODO: All functions should be using try/except to catch errors and log them
# TODO: Race conditions should be investigated - handled by using transactions and locking
# TODO:

def create_connection(db_file='database.db'):
    """ create a database connection to a SQLite database """
    conn = sqlite3.connect(db_file)
    return conn

# This function will allocate a task to a participant (prolific_id)
# The allocated task will be updated to have the status 'allocated' and the prolific_id, and session_id and time_allocated will be set.
# It will return the task ID and the task number
# First the function will check if the participant has already been allocated a task (one that is not of status "completed") and return that task if so
# If not, it will find a task that has been assigned less than three times and assign it to the participant
# If no tasks are available, it will return None
# TODO: Must ensure this wont crash, use try/except and log errors
# TODO: Make sure participant is not assigned the same task twice (check prolific_id against task_id in completed tasks)
# Returns: (task_id, task_number) or None if no tasks are available
def allocate_task(prolific_id, session_id):
    conn = create_connection()
    cursor = conn.cursor()

    # Check if the participant has already been allocated a task
    cursor.execute("SELECT id, task_number FROM tasks WHERE prolific_id=? AND status!='completed'", (prolific_id,))
    allocated_tasks = cursor.fetchall()
    if len(allocated_tasks) > 0:
        # Return the first allocated task
        return allocated_tasks[0]

    # Find a task that has been assigned less than three times
    cursor.execute("SELECT id, task_number FROM tasks WHERE status='waiting'")
    waiting_tasks = cursor.fetchall()
    for task_id, task_number in waiting_tasks:
        cursor.execute("SELECT COUNT(*) FROM tasks WHERE task_number=? AND status='allocated'", (task_number,))
        num_allocated = cursor.fetchone()[0]
        if num_allocated < 3:
            # Task found, assign the task to the user
            cursor.execute("UPDATE tasks SET status='allocated', prolific_id=?, time_allocated=?, session_id=? WHERE id=?", (prolific_id, datetime.now(), session_id, task_id))
            conn.commit()
            conn.close()
            return task_id, task_number
    else:
        return None

# This function will be run periodically and expire tasks that have been allocated for too long
# eg 2023-11-27 15:45:30.123456
# TODO: Must ensure this wont crash, use try/except and log errors
# TODO: Must work out where to set time_limit for whole study (eg 1 hour) - likely in main.py or a config.py
def expire_tasks(time_limit=3600):
    conn = create_connection()
    cursor = conn.cursor()
    # Get the current time
    current_time = datetime.now()
    # Get the IDs of all allocated tasks
    cursor.execute("SELECT id, time_allocated FROM tasks WHERE status='allocated'")
    allocated_tasks = cursor.fetchall()
    # Iterate through the allocated tasks
    for task_id, time_allocated in allocated_tasks:
        print(task_id, time_allocated)

        if time_allocated is None:
            print("Uh oh... time_allocated is None")
            continue

        # Calculate the time difference
        time_diff = (current_time - datetime.strptime(time_allocated, '%Y-%m-%d %H:%M:%S.%f')).total_seconds()
        # If the time difference is more than the time limit, expire the task
        if time_diff > time_limit:
            cursor.execute("UPDATE tasks SET status='waiting', prolific_id = NULL, time_allocated = NULL, session_id = NULL WHERE id=?", (task_id,))
    # Commit the changes and close the connection
    conn.commit()
    conn.close()

# TODO: Make sure task is allocated to participant before completing it (check status='allocated')
def complete_task(id, json_string, prolific_id):
    conn = create_connection()
    cursor = conn.cursor()

    # Update the task status to 'completed'
    cursor.execute("UPDATE tasks SET status='completed' WHERE id=?", (id,))
    # Add the result to the results table

    cursor.execute("INSERT INTO results (id, json_string, prolific_id) VALUES (?, ?, ?)", (id, json_string, prolific_id))
    # Commit the changes and close the connection

    conn.commit()
    conn.close()

def get_all_tasks():
    try:
        with create_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks")
            tasks = cursor.fetchall()
            return tasks
    except sqlite3.Error as e:
        print(f"An error occurred: {e}")
        return None

def get_specific_result(result_id):
    try:
        with create_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM results WHERE id=?", (result_id,))
            result = cursor.fetchone()
            return result
    except sqlite3.Error as e:
        print(f"An error occurred: {e}")
        return None


#expire_tasks()
#complete_task('9f28d264-434b-433d-abcf-4124bb97c019', '{"test": 1}', '1234')



# Allocate a task to a new participant
#result = allocate_task("dummy11", "session1")
#print("Test 1 Result:", result)

# Attempt to allocate a task to a participant who already has an allocated but not completed task
#id, task = allocate_task("dummy12", "session1")
#complete_task(id, '{"test": 1}', 'dummy12')
#print("Test 2 Result:", id)




#print(get_specific_result('8cc2c7b2-83e3-4a7d-aeb2-0efc0ce9cf39'))