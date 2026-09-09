import traceback
from app.services.gemini_service import answer_query

try:
    print(answer_query("test prompt"))
except Exception as e:
    traceback.print_exc()
