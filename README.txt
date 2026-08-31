
STOCHASTIC CHALLENGE - INTERNET VERSION
=======================================

This version is designed to be placed on a public web host.
Students do NOT need to be on the same Wi-Fi as the teacher.

Recommended simple deployment: Render.com

FILES
-----
app.py
requirements.txt
render.yaml
Procfile
templates/teacher.html
templates/student.html

WHAT CHANGED FROM THE LOCAL VERSION
-----------------------------------
1. The QR code automatically uses the public website address.
2. Students can join from Wi-Fi OR cellular data.
3. The game uses SQLite instead of Python-only memory.
4. It is configured for a one-worker Gunicorn web server.

RENDER DEPLOYMENT - SIMPLE STEPS
--------------------------------
1. Create a free GitHub account if you do not already have one.
2. Create a new GitHub repository, for example:
      stochastic-challenge
3. Upload ALL files from this folder to that repository.

4. Go to:
      https://render.com

5. Sign in and choose:
      New +  ->  Web Service

6. Connect your GitHub repository.

7. Render should detect the render.yaml settings.
   If it asks manually, use:

   Build Command:
      pip install -r requirements.txt

   Start Command:
      gunicorn -w 1 -b 0.0.0.0:$PORT app:app

8. Deploy.

9. Render will give you a public address similar to:
      https://stochastic-challenge-xxxx.onrender.com

10. Teacher page:
      https://YOUR-ADDRESS/teacher

11. Click CREATE GAME.

12. Students scan the QR code.
    They can join from ANY Internet connection.

IMPORTANT
---------
On some free hosting plans, the website may sleep after inactivity.
Open the teacher page several minutes before class so it is awake.

DATA
----
The SQLite database is stored on the server filesystem.
For a classroom activity, export your CSV at the end of the game.

The app supports:
- room codes
- student names
- 1-6 predictions
- lock predictions
- physical die result entry
- automatic scoring
- live top 5
- final ranking
- expected random score
- class average
- most popular choice
- most frequently rolled number
- CSV export
