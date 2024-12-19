from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, PasswordField
from wtforms.validators import DataRequired, Optional, URL

class APISettingsForm(FlaskForm):
    square_access_token = StringField('Square Access Token', 
                                    validators=[Optional()],
                                    description="Your Square API access token")
    submit = SubmitField('Save Settings')
