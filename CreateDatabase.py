# This is a python script that will create the required database tasks table.
# DO NOT RUN THIS SCRIPT IF THE DATABASE ALREADY EXISTS. IT WILL DELETE THE EXISTING DATABASE AND CREATE A NEW ONE.

COMPLETIONS_PER_TASK = 3  # Number of times each task should be completed by different participants
NUMBER_OF_TASKS = 60  # Number of tasks to create in the database

import sqlite3
from uuid import uuid4

# Creates the DB file if it doesn't exist, and creates the tables if they don't exist.
def initDatabase():
    # Connect to SQLite database (or create it if it doesn't exist)
    conn = sqlite3.connect('database.db')
    # Create a cursor object using the cursor() method
    cursor = conn.cursor()
    # Define the schema for the 'tasks' table
    create_tasks_table = '''
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    task_number INTEGER,
    prolific_id TEXT,
    time_allocated TEXT,
    session_id TEXT,
    status TEXT CHECK( status IN ('allocated', 'waiting', 'completed') )
);
'''

    # Define the schema for the 'results' table
    create_results_table = '''
CREATE TABLE IF NOT EXISTS results (
    id TEXT PRIMARY KEY,
    json_string TEXT,
    prolific_id TEXT
);
'''
    # Execute the SQL commands to create tables
    cursor.execute(create_tasks_table)
    cursor.execute(create_results_table)
    # Commit the changes and close the connection
    conn.commit()
    conn.close()

def initTasks(num_tasks, db_file='database.db'):
    """
    Initializes a specified number of tasks in the 'tasks' table with default values.
    Each task will have multiple entries (as defined by COMPLETIONS_PER_TASK) with unique IDs but the same task number.

    :param num_tasks: The number of tasks to initialize.
    :param db_file: The SQLite database file.
    """
    # Connect to the SQLite database
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # Default status for new tasks
    default_status = 'waiting'

    # Prepare the SQL query for inserting a new task
    insert_task_query = '''
    INSERT INTO tasks (id, task_number, prolific_id, time_allocated, session_id, status)
    VALUES (?, ?, NULL, NULL, NULL, ?);
    '''

    # Insert the specified number of tasks, repeated according to COMPLETIONS_PER_TASK
    for task_number in range(1, num_tasks + 1):
        for _ in range(COMPLETIONS_PER_TASK):
            # Generate a unique ID for the task
            task_id = str(uuid4())
            # Execute the SQL query
            cursor.execute(insert_task_query, (task_id, task_number, default_status))

    # Commit the changes and close the connection
    conn.commit()
    conn.close()



# --------------------------------------------------

initDatabase()
initTasks(NUMBER_OF_TASKS)
