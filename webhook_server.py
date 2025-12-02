from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from bson.objectid import ObjectId
import os
from dotenv import load_dotenv
from paypal_manager import create_payment, execute_payment

load_dotenv()

app = Flask(__name__)

# ---------------- CORS FIXED (NO MORE FAILED TO FETCH) ----------------
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    supports_credentials=True,
    methods=["GET", "POST", "OPTIONS"]
)

# ---------------- MongoDB Connection ----------------
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
db = client.betting_bot_db
plans_collection = db.plans


# ---------------- Seed DB if Empty ----------------
def seed_database():
    if plans_collection.count_documents({}) == 0:
        plans_collection.insert_many([
            {"name": "Basic", "price": 15.0},
            {"name": "Premium", "price": 20.0}
        ])
        print("Database seeded with default plans.")

seed_database()


# ---------------- Helper to Convert MongoDB → JSON ----------------
def serialize_doc(doc):
    doc["_id"] = str(doc["_id"])
    return doc


# ---------------- GET PLANS ----------------
@app.route('/plans', methods=['GET'])
def get_plans():
    try:
        plans = list(plans_collection.find())
        return jsonify([serialize_doc(p) for p in plans]), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ---------------- UPDATE PLAN (POST + OPTIONS FIXED) ----------------
@app.route('/update-plan', methods=['POST', 'OPTIONS'])
def update_plan():

    # handle preflight request (this was causing Failed to Fetch)
    if request.method == "OPTIONS":
        return jsonify({"status": "CORS_OK"}), 200

    try:
        data = request.get_json()
        if not data or "name" not in data or "new_price" not in data:
            return jsonify({"success": False, "message": "Invalid payload"}), 400

        name = data["name"]
        price = float(data["new_price"])

        result = plans_collection.update_one({"name": name}, {"$set": {"price": price}})

        if result.matched_count == 0:
            return jsonify({"success": False, "message": f"Plan '{name}' not found"}), 404

        updated_plan = plans_collection.find_one({"name": name})
        return jsonify({
            "success": True,
            "message": f"Plan '{name}' updated successfully!",
            "plan": serialize_doc(updated_plan)
        }), 200

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500



# ---------------- PayPal Routes ----------------
@app.route('/paypal/create', methods=['POST'])
def paypal_create():
    try:
        data = request.get_json()
        if not data or "amount" not in data:
            return jsonify({"success": False, "message": "Invalid payload, 'amount' is required"}), 400

        amount = data["amount"]
        result = create_payment(amount)

        if result["success"]:
            return jsonify({"success": True, "approval_url": result["approval_url"], "payment_id": result["payment_id"]}), 200
        else:
            return jsonify({"success": False, "message": result["message"]}), 500
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/paypal/execute', methods=['POST'])
def paypal_execute():
    try:
        data = request.get_json()
        if not data or "paymentId" not in data or "PayerID" not in data:
            return jsonify({"success": False, "message": "Invalid payload, 'paymentId' and 'PayerID' are required"}), 400

        payment_id = data["paymentId"]
        payer_id = data["PayerID"]
        result = execute_payment(payment_id, payer_id)

        if result["success"]:
            return jsonify({"success": True, "message": result["message"], "transaction": result["transaction"], "status": result["status"]}), 200
        else:
            return jsonify({"success": False, "message": result["message"], "transaction": result["transaction"], "status": result["status"]}), 500
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ---------------- RUN SERVER ----------------
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
