import re

# In app/db/models.py
with open("app/db/models.py", "r") as f:
    models_content = f.read()
models_content = models_content.replace("class WhatsappSessions(Base):", "class ChatSessions(Base):")
models_content = models_content.replace("__tablename__ = \"whatsapp_sessions\"", "__tablename__ = \"chat_sessions\"")
with open("app/db/models.py", "w") as f:
    f.write(models_content)

# In app/sessions.py
with open("app/sessions.py", "r") as f:
    sessions_content = f.read()
sessions_content = sessions_content.replace("WhatsappSessions", "ChatSessions")
with open("app/sessions.py", "w") as f:
    f.write(sessions_content)
