# Beira - Multi-Platform Order Management System

A web application to manage orders from multiple e-commerce platforms (Etsy, Square, and Shippo) with customer management capabilities.

## Features

- Unified order view from multiple platforms:
  - Etsy.com orders
  - Square Online orders
  - Shippo.com shipments
- Customer management with purchase history
- Customer messaging system
- Secure Google authentication
- Restricted access management

## Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables in `.env` file:
```
FLASK_APP=app
FLASK_ENV=development
SECRET_KEY=your-secret-key
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
ETSY_API_KEY=your-etsy-api-key
SQUARE_ACCESS_TOKEN=your-square-access-token
ALLOWED_EMAILS=email1@example.com,email2@example.com
```

4. Initialize the database:
```bash
flask db upgrade
```

5. Run the application:
```bash
flask run
```

## API Integration

This application integrates with:
- Etsy API for order management
- Square API for payment and order processing
- Shippo API for shipping management

## Etsy Integration Setup

### Prerequisites
1. Create an Etsy Developer Account
   - Go to [Etsy Developer Portal](https://www.etsy.com/developers/)
   - Create a new application

### OAuth Configuration
- **Redirect URI**: `http://localhost:5000/connect/etsy/callback`
- **Required Scopes**:
  - `transactions.r`: Read order transactions
  - `listings.r`: Read shop listings
  - `shops.r`: Read shop information
  - `profile.r`: Read user profile

### Troubleshooting
- **Application Not Approved**
  - Etsy requires manual review of OAuth applications
  - After submitting your application, wait for Etsy's approval
  - Check your developer dashboard for status updates

- **Common Configuration Errors**
  1. Mismatched Redirect URI
     - Ensure the URI exactly matches what's in your Etsy app settings
     - Case-sensitive and must include protocol (http/https)

  2. Incorrect Scopes
     - Verify requested scopes match your application's intended functionality
     - Request only the scopes you need

  3. API Key Issues
     - Double-check your API key (keystring) in `.env`
     - Ensure it matches the key in the Etsy Developer Portal

### Debugging
- Check application logs for detailed error messages
- Verify `.env` configuration
- Confirm Etsy Developer Portal settings

### Security Notes
- Never commit your `.env` file with real credentials
- Use environment-specific configurations
- Rotate tokens periodically

### Development Workflow
1. Create Etsy Developer Account
2. Register Application
3. Configure Redirect URI
4. Set Scopes
5. Obtain API Key and Shared Secret
6. Update `.env` file
7. Test OAuth Flow

## Security

- Authentication is handled through Google OAuth
- Access is restricted to specifically allowed email addresses
- All sensitive information is stored securely using environment variables
