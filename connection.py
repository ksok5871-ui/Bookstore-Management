import mysql.connector

def get_db_connection():
    connection = mysql.connector.connect(
        host='localhost',
        user='root',          
        password='',
        database='bookstore_db'
    )
    return connection
