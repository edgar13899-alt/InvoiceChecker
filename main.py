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
    vertexai.init(project=project_id, location="us-central1", credentials=credentials)
    
    # Connect Firestore Database
    db = firestore.Client(project=project_id, credentials=credentials)
    return db

db = setup_cloud_connections()

# 2. File Upload (Only need the invoice now!)
invoice_file = st.file_uploader("Upload Invoice Document", type=["png", "jpg", "jpeg", "pdf"])

if st.button("Process Invoice") and invoice_file:
    try:
        document_part = Part.from_data(data=invoice_file.getvalue(), mime_type=invoice_file.type)
        model = GenerativeModel('gemini-3.0-pro')
        
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
        
        with st.spinner("AI is reading the invoice and checking the database..."):
            response = model.generate_content([document_part, prompt])
            result_text = response.text.replace('```json', '').replace('```', '').strip()
            invoice_data = json.loads(result_text)
            
            vendor_name = invoice_data["Vendor_Name"]
            st.subheader(f"🏢 Vendor: {vendor_name}")
            
            comparison_results = []
            
            # 3. Check the Database for each item
            for item in invoice_data["Items"]:
                item_name = item["Item_Name"]
                new_price = float(item["New_Price"])
                
                # Look inside Firestore for this specific vendor and item
                doc_ref = db.collection("vendor_prices").document(f"{vendor_name}_{item_name}")
                doc = doc_ref.get()
                
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
        vendor_name = st.session_state['ready_to_save']["Vendor_Name"]
        with st.spinner("Saving to enterprise database..."):
            for item in st.session_state['ready_to_save']["Items"]:
                item_name = item["Item_Name"]
                new_price = float(item["New_Price"])
                
                # Write the new price into Firestore
                db.collection("vendor_prices").document(f"{vendor_name}_{item_name}").set({
                    "vendor": vendor_name,
                    "item": item_name,
                    "last_price": new_price
                })
        st.success("Prices securely saved! The app will remember these for the next invoice.")
        del st.session_state['ready_to_save'] # Clear the state
