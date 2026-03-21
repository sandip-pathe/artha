import asyncio
from app.agent import run_artha
from app.db.session import SessionLocal

TESTS = [
    {
        "name": "Test 1 - Text query",
        "kwargs": {
            "merchant_phone": "918767394523",
            "user_input": "aaj kitna hua?",
            "input_type": "text",
            "is_morning": False,
            "is_evening": False,
            "ocr_text": None,
        },
        "expect_tools": ["get_sales_summary"],
    },
    {
        "name": "Test 2 - Voice intent",
        "kwargs": {
            "merchant_phone": "918767394523",
            "user_input": "Suresh ko 300 ka udhaar diya",
            "input_type": "voice",
            "is_morning": False,
            "is_evening": False,
            "ocr_text": None,
        },
        "expect_tools": ["log_udhaar"],
    },
    {
        "name": "Test 3 - Image OCR payment",
        "kwargs": {
            "merchant_phone": "918767394523",
            "user_input": "payment check",
            "input_type": "image",
            "is_morning": False,
            "is_evening": False,
            "ocr_text": "Paid INR 450 to Sharma General Store T260321153045DEMO0001",
        },
        "expect_tools": ["search_payment"],
    },
    {
        "name": "Test 4 - Morning trigger",
        "kwargs": {
            "merchant_phone": "918767394523",
            "user_input": "good morning",
            "input_type": "text",
            "is_morning": True,
            "is_evening": False,
            "ocr_text": None,
        },
        "expect_tools": ["get_morning_brief"],
    },
    {
        "name": "Test 5 - Unknown question",
        "kwargs": {
            "merchant_phone": "918767394523",
            "user_input": "mujhe nahi pata kya poochhun",
            "input_type": "text",
            "is_morning": False,
            "is_evening": False,
            "ocr_text": None,
        },
        "expect_tools": [],
    },
]


async def run_tests() -> None:
    with SessionLocal() as db:
        for case in TESTS:
            result = await run_artha(
                db_session=db,
                conversation_history=[],
                **case["kwargs"],
            )

            tools_called = result.get("tools_called") or []
            response_text = (result.get("response_text") or "").replace("\n", " ").strip()
            expected = case["expect_tools"]

            if expected:
                passed = all(tool in tools_called for tool in expected)
            else:
                passed = len(response_text) > 0

            print(f"{case['name']} :: {'PASS' if passed else 'FAIL'}")
            print(f"  intent={result.get('intent')}")
            print(f"  tools_called={tools_called}")
            print(f"  needs_recheck={result.get('needs_recheck')}")
            print(f"  response_preview={response_text[:220]}")
            print("-")


if __name__ == "__main__":
    asyncio.run(run_tests())
