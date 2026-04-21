import streamlit as st
import pandas as pd
import vertexai
from vertexai.generative_models import GenerativeModel, Part
from google.oauth2 import service_account
from google.cloud import firestore
import json

# Set up the look of the web app
st.set_page_config(page_title="Invoice Database Tracker", layout="wide")
st.title("🧾 Smart Invoice Tracker (Firestore Edition)")
st.markdown("Upload a new invoice. The app will check your database for the last price you paid.")

# 1. Connect to Google Cloud (Both AI and Database)
@st.cache_resource
def setup_cloud_connections():
    key_dict = json.loads(st.secrets["GCP_KEY"])
    credentials = service_account.Credentials.from_service_account_info(key_dict)
    project_id = st.secrets["GCP_PROJECT"]
    
    # Connect Vertex AI
    vertexai.init(project=project_id, location="global", credentials=credentials)
    
    # Connect Firestore Database
    db = firestore.Client(project=project_id, credentials=credentials, database="lavaquitainvoices")
    return db

db = setup_cloud_connections()

# 2. File Upload (Only need the invoice now!)
invoice_file = st.file_uploader("Upload Invoice Document", type=["png", "jpg", "jpeg", "pdf"])

if st.button("Process Invoice") and invoice_file:
    try:
        document_part = Part.from_data(data=invoice_file.getvalue(), mime_type=invoice_file.type)
        model = GenerativeModel('gemini-3.1-pro-preview')
        
        prompt = """
        You are an expert accountant. Read this invoice carefully.
        1. Identify the name of the Vendor/Supplier.
        2. Extract the line items and their unit prices.
        3. Return ONLY a valid JSON object with the following structure:
        {
            "Vendor_Name": "Name of the company",
            "Items": [
                {
                    "Item_Name": "Exact name on invoice",
                    "New_Price": 12.50
                }
            ]
        }
        """
        
        with st.spinner("AI is reading the invoice..."):
            response = model.generate_content([document_part, prompt])
            raw_text = response.text
            
            # --- NEW ERROR-PROOF LOGIC START ---
            try:
                # 1. Find the first '{' and last '}' to ignore any extra "chat" the AI added
                start = raw_text.find('{')
                end = raw_text.rfind('}') + 1
                clean_json = raw_text[start:end]
                
                # 2. Fix the most common AI mistake: single quotes instead of double quotes
                # (This is often what causes the "enclosed in double quotes" error)
                invoice_data = json.loads(clean_json)
                
            except json.JSONDecodeError:
                # 3. If it still fails, try a "Deep Clean" for quotes
                import re
                # This fixes keys that are missing quotes or have single quotes
                fixed_json = re.sub(r"([{,])\s*([^'\"\[\]{}]+)\s*:", r'\1"\2":', clean_json)
                fixed_json = fixed_json.replace("'", '"')
                invoice_data = json.loads(fixed_json)
            # --- NEW ERROR-PROOF LOGIC END ---

            vendor_name = invoice_data["Vendor_Name"].replace("/", "-")
            st.subheader(f"🏢 Vendor: {vendor_name}")
            
            # ... (The rest of the items loop stays the same)
            comparison_results = []
            
            for item in invoice_data["Items"]:
                # Clean the item name so it doesn't have slashes
                item_name = item["Item_Name"].replace("/", "-")
                new_price = float(item["New_Price"])
                
                # Create a safe ID for the document
                doc_id = f"{vendor_name}_{item_name}"
                
                # Look inside Firestore
                doc_ref = db.collection("vendor_prices").document(doc_id)
                doc = doc_ref.get()
                
                # ... (the rest of your logic follows)
                
                if doc.exists:
                    last_price = doc.to_dict().get("last_price")
                    price_change = new_price - last_price
                    if price_change > 0:
                        status = "Increased"
                    elif price_change < 0:
                        status = "Decreased"
                    else:
                        status = "Unchanged"
                else:
                    last_price = "No History"
                    price_change = "N/A"
                    status = "New Item"
                
                comparison_results.append({
                    "Item": item_name,
                    "Last Paid Price": last_price,
                    "New Invoice Price": new_price,
                    "Difference": price_change,
                    "Status": status
                })
            
            # Display the results
            result_df = pd.DataFrame(comparison_results)
            
            def highlight_increases(val):
                if val == 'Increased': return 'background-color: #ff9999'
                elif val == 'Decreased': return 'background-color: #99ff99'
                elif val == 'New Item': return 'background-color: #ffff99'
                return ''
                
            st.dataframe(result_df.style.map(highlight_increases, subset=['Status']), use_container_width=True)
            
            # Save the new data temporarily so we can update the database if the user approves
            st.session_state['ready_to_save'] = invoice_data

    except Exception as e:
        st.error(f"An error occurred: {e}")

# 4. The "Memory" Button
if 'ready_to_save' in st.session_state:
    st.warning("Please review the prices above. If everything looks correct, save them to the database for next time.")
    if st.button("💾 Save New Prices to Database"):
        # Clean the vendor name again
        vendor_name = st.session_state['ready_to_save']["Vendor_Name"].replace("/", "-")
        with st.spinner("Saving to enterprise database..."):
            for item in st.session_state['ready_to_save']["Items"]:
                # Clean the item name again
                item_name = item["Item_Name"].replace("/", "-")
                new_price = float(item["New_Price"])
                
                doc_id = f"{vendor_name}_{item_name}"
                db.collection("vendor_prices").document(doc_id).set({
                    "vendor": vendor_name,
                    "item": item_name,
                    "last_price": new_price
                })
        st.success("Prices securely saved! The app will remember these for the next invoice.")
        del st.session_state['ready_to_save'] # Clear the state
