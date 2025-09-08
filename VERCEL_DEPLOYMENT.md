# Vercel Deployment Guide

## Changes Made

1. **Fixed Vercel Configuration**: Updated `vercel.json` to use the proper structure without deprecated `builds` configuration
2. **Created Vercel Handler**: Added `api/index.py` as the entry point for Vercel
3. **Fixed Environment Variables**: Updated `server.py` to handle missing environment variables gracefully
4. **Added Health Check**: Added `/health` endpoint for monitoring

## Environment Variables Required

You need to set these environment variables in your Vercel project settings:

1. Go to your Vercel project dashboard
2. Navigate to Settings > Environment Variables
3. Add the following variables:

```
MONGO_URL=mongodb+srv://username:password@cluster.mongodb.net/
DB_NAME=statustrackr
EMAIL_HOST=mail.moracity.com
EMAIL_PORT=465
EMAIL_USER=info@moracity.com
EMAIL_PASSWORD=your_password
EMAIL_FROM=info@moracity.com
EMAIL_FROM_NAME=Moracity Car-Rental
```

## Project Structure

```
backend/
├── api/
│   ├── index.py          # Vercel entry point
│   └── requirements.txt  # Dependencies for Vercel
├── server.py             # Main FastAPI application
├── vercel.json          # Vercel configuration
└── requirements.txt     # Main dependencies
```

## Testing the Deployment

After deployment, test these endpoints:

- `GET /` - Main API info
- `GET /health` - Health check
- `GET /api/` - API root
- `GET /docs` - API documentation

## Troubleshooting

If you still get errors:

1. Check Vercel function logs in the dashboard
2. Verify all environment variables are set
3. Ensure MongoDB connection string is correct
4. Check that all dependencies are in `api/requirements.txt`
