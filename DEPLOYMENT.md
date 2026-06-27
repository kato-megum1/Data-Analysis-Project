# Quick Deployment

Deploy this project as a Python web service. The current app is a Flask API plus a static HTML frontend, so a Python web service host is a better fit than a static-only deploy.

## Render

1. Push the project to GitHub or GitLab.
2. Create a Render Blueprint or Web Service and connect the repository.
3. If you use Blueprint, Render reads `render.yaml`.
4. If you configure the service manually:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn server:app --bind 0.0.0.0:$PORT --workers 1 --timeout 180`
   - Health Check Path: `/healthz`
5. Add `DEEPSEEK_API_KEY` in Render environment variables. Do not commit API keys.
6. Open the URL Render gives you after deployment.

## Demo Notes

- If `DEEPSEEK_API_KEY` is set on the server, friends and interviewers can use the app without entering their own key.
- If the environment variable is not set, users can still enter a key in the settings drawer; it is stored only in browser `localStorage`.
- Hosted file storage is usually ephemeral, so generated reports are suitable for demos, not long-term archiving.
