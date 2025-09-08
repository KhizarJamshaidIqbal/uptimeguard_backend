# StatusTrackr Backend Deployment to Render.com

## Prerequisites

1. A Render.com account
2. A MongoDB Atlas account (or another MongoDB provider)
3. Your MongoDB connection string

## Deployment Steps

1. **Fork this repository** or prepare your code for deployment.

2. **Create a MongoDB database**:
   - If you haven't already, create a MongoDB Atlas cluster.
   - Get your MongoDB connection string.

3. **Deploy to Render.com**:
   - Go to [Render Dashboard](https://dashboard.render.com/)
   - Click "New" and select "Web Service"
   - Connect your GitHub repository or upload your code
   - Set the following configuration:
     - Name: `statustrackr-api`
     - Runtime: Python 3
     - Build Command: `pip install -r requirements.txt`
     - Start Command: `uvicorn server:app --host 0.0.0.0 --port $PORT`
     - Plan: Free (or choose a paid plan for production)

4. **Set Environment Variables**:
   In the Render dashboard, go to your service settings and add the following environment variables:
   - `MONGO_URL`: Your MongoDB connection string
   - `DB_NAME`: `statustrackr`
   - `DEBUG`: `false`

5. **Deploy**:
   - Click "Create Web Service"
   - Render will automatically build and deploy your application
   - The deployment URL will be available in the dashboard

## Configuration

The application uses environment variables for configuration. Make sure to set these in your Render.com dashboard:

- `MONGO_URL`: MongoDB connection string
- `DB_NAME`: Database name (default: statustrackr)
- `DEBUG`: Enable/disable debug mode (default: false)

## Notes

- Render.com automatically provides the `$PORT` environment variable
- The application will be available at the URL provided by Render.com
- CORS is enabled for all origins in the application