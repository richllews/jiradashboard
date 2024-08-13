Constants.py 
This holds the authentication settings for the dashboard as well as a constant for the project. 
All you need to do is add your details in the fields with placeholders, for example USER_EMAIL = '<YOUR EMAIL>'

Imports.py
This holds the packages that you need to have installed.
Install them by using pip install <package>, for example pip install pandas

dashboard.py
This is where the calls to jira and the magic happens

Running the script
Its simple really:
1) Open the Terminal (on mac)
2) Navigate to the relevant directory using cd <directory>
3) Type: python3 dashboard.py
4) You will be asked for the Board ID (which you can see when you look at the URL of your jira board)
5) You will be a message that the html file has been created in your directory
6) Open the html file
