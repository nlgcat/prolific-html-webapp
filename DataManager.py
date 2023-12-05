import sqlite3
from datetime import datetime

# TODO: Race conditions should be investigated - handled by using transactions and locking
# TODO: What happens when a worker returns results that have not been allocated to them?
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
def allocate_task(prolific_id, session_id):
    """
    Allocates a task to a participant based on given criteria.

    Parameters:
    prolific_id (str): The ID of the participant.
    session_id (str): The session ID.

    Returns:
    tuple: (task_id, task_number) if a task is allocated, None if no tasks are available,
           or a message and -1 in case of a database error.
    """
    try:
        with create_connection() as conn:
            cursor = conn.cursor()

            # Check if the participant has an incomplete allocated task
            cursor.execute("SELECT id, task_number FROM tasks WHERE prolific_id=? AND status!='completed'", (prolific_id,))
            allocated_tasks = cursor.fetchall()
            if allocated_tasks:
                return allocated_tasks[0]

            # Find a task that hasn't been assigned to this participant and has been assigned less than three times
            cursor.execute("""
                SELECT id, task_number FROM tasks 
                WHERE status='waiting' AND task_number NOT IN (
                    SELECT task_number FROM tasks WHERE prolific_id=? AND status='completed'
                )
            """, (prolific_id,))
            waiting_tasks = cursor.fetchall()
            for task_id, task_number in waiting_tasks:
                cursor.execute("SELECT COUNT(*) FROM tasks WHERE task_number=? AND status='allocated'", (task_number,))
                num_allocated = cursor.fetchone()[0]
                if num_allocated < 3:
                    cursor.execute("UPDATE tasks SET status='allocated', prolific_id=?, time_allocated=?, session_id=? WHERE id=?",
                                   (prolific_id, datetime.utcnow(), session_id, task_id))
                    conn.commit()
                    return task_id, task_number
            return None

    except sqlite3.Error as e:
        # Consider logging the error
        return f"Database Error - {e}", -1

# This function will be run periodically and expire tasks that have been allocated for too long
# eg 2023-11-27 15:45:30.123456
def expire_tasks(time_limit=3600):
    """
    Expires tasks that have been allocated for longer than a specified time limit.

    This function checks all tasks with the status 'allocated' and compares the
    time they were allocated with the current time. If the time elapsed since
    allocation is greater than the time limit, the task's status is reset to 'waiting'.

    Parameters:
    time_limit (int): The time limit in seconds. Tasks allocated for longer than this
                      duration will be expired. Defaults to 3600 seconds (1 hour).

    Returns:
    None: The function doesn't return a value but updates the tasks in the database
          if they exceed the time limit.
    """
    try:
        with create_connection() as conn:
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
    except sqlite3.Error as e:
        print(f"An error occurred trying to expire tasks: {e}")

# TODO: Make sure task is allocated to participant before completing it (check status='allocated') - working on this, maybe not needed.
# Note: Removing the conn.close() is the suggested fix for DB locking with try except. Garbage collection will close the connection when the function ends.
def complete_task(id, json_string, prolific_id):
    """
    Completes a task assigned to a participant and records the result.

    This function checks if the task with the given ID is allocated to the participant
    identified by their prolific ID. If so, it updates the task's status to 'completed'
    and inserts the task result (provided as a JSON string) into the results table.

    Parameters:
    id (str): The ID of the task to be completed.
    json_string (str): A JSON string representing the result of the task.
    prolific_id (str): The ID of the participant who is completing the task.

    Returns:
    int: -1 if the task is not allocated to the participant, otherwise no explicit return value.
    """
    try:
        with create_connection() as conn:
            cursor = conn.cursor()

            # Check if the task is allocated to the participant
            cursor.execute("SELECT id FROM tasks WHERE id=? AND prolific_id=?", (id, prolific_id))
            task = cursor.fetchone()
            if task is None:
                print("Task not allocated to participant... not completing tasks.")
                #print(f"Task:" + str(json_string)) # This is where this would be logged - we don't need to unless debugging
                return -1

            # Update the task status to 'completed'
            cursor.execute("UPDATE tasks SET status='completed' WHERE id=?", (id,))
            # Add the result to the results table

            cursor.execute("INSERT INTO results (id, json_string, prolific_id) VALUES (?, ?, ?)", (id, json_string, prolific_id))
            # Commit the changes and close the connection

            conn.commit()

    except sqlite3.Error as e:
        print(f"An error occurred trying to complete a task.: {e}")

def get_all_tasks():
    """
    Retrieves all tasks from the tasks table in the database.

    This function queries the database for all entries in the tasks table.
    It is intended to fetch every task, regardless of its status or other attributes.

    Returns:
    list: A list of tuples, where each tuple represents a task with all its database fields.
          Returns None if a database error occurs.
    """
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
    """
    Retrieves a specific result from the results table based on the result ID.

    This function is designed to query the database for a single entry in the results
    table that matches the provided result ID. It returns the specific result associated
    with that ID.

    Parameters:
    result_id (int): The ID of the result to be retrieved.

    Returns:
    tuple: A tuple representing the result with all its database fields, or None if
           the result is not found or a database error occurs.
    """
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