import streamlit as st
import pandas as pd
import vertexai
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig
from google.oauth2 import service_account
from google.cloud import firestore
import json

# --- 1. APP CONFIGURATION ---
st.set_page_config(page_title="La Vaquita Invoice Tracker", layout="wide", page_icon="🧾")
st.title("🧾 La Vaquita: Smart Invoice Tracker")
st.markdown("### Powered by Gemini 3.1 Pro & Firestore")
st.info("Upload a new vendor invoice. The AI will read it and compare prices against your previous history.")

# --- 2. SECURE CONNECTIONS ---
@st.cache_resource
def setup_enterprise_connections():
    # Load your secret JSON badge from the Streamlit vault
    key_dict = json.loads(st.secrets["GCP_KEY"])
    credentials = service_account.Credentials.from_service_account_info(key_dict)
    project_id = st.secrets["GCP_PROJECT"]
    
    # 3.1 Pro Preview requires the 'global' location endpoint
    vertexai.init(project=project_id, location="global", credentials=credentials)
    
    # Connect to your Firestore 'default' database
    db = firestore.Client(project=project_id, credentials=credentials)
    return db

db = setup_enterprise_connections()

# --- 3. FILE UPLOADER ---
invoice_file = st.file_uploader("Upload Invoice (Digital PDF is best, or clear Image)", type=["png", "jpg", "jpeg", "pdf"])

if st.button("🚀 Process Invoice") and invoice_file:
    try:
        # --- THE BULLETPROOF TEMPLATE (SCHEMA) ---
        # This locks the AI into using only the names we want
        response_schema = {
            "type": "OBJECT",
            "properties": {
                "Vendor_Name": {"type": "STRING"},
                "Items": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "Item_Name": {"type": "STRING"},
                            "New_Price": {"type": "NUMBER"},
                        },
                        "required": ["Item_Name", "New_Price"]
                    }
                }
            },
            "required": ["Vendor_Name", "Items"]
        }

        # --- AI GENERATION CONFIG ---
        model = GenerativeModel('gemini-3.1-pro-preview')
        config = GenerationConfig(
            response_mime_type="application/json",
            response_schema=response_schema
        )
        
        prompt = "Extract the vendor name and every line item with its individual unit price from this invoice."

        with st.spinner("Gemini 3.1 is analyzing the document..."):
            # Prepare the file for the AI
            document_part = Part.from_data(data=invoice_file.getvalue(), mime_type=invoice_file.type)
            
            # Send to the global engine
            response = model.generate_content([document_part, prompt], generation_config=config)
            
            # Convert text response to usable Python data
            invoice_data = json.loads(response.text)
            
            # Clean vendor name for the database path (No slashes allowed!)
            vendor_name = invoice_data["Vendor_Name"].replace("/", "-").strip()
            st.subheader(f"🏢 Vendor: {vendor_name}")
            
            comparison_results = []
            
            # --- DATABASE CHECKING LOOP ---
            for item in invoice_data["Items"]:
                # Clean item name for the path
                item_name = item["Item_Name"].replace("/", "-").strip()
                new_price = float(item["New_Price"])
                
                # Create the unique ID: Vendor_Item
                doc_id = f"{vendor_name}_{item_name}"
                doc_ref = db.collection("vendor_prices").document(doc_id)
                doc = doc_ref.get()
                
                if doc.exists:
                    last_price = doc.to_dict().get("last_price")
                    price_change = new_price - last_price
                    
                    if price_change > 0: status = "Increased"
                    elif price_change < 0: status = "Decreased"
                    else: status = "Unchanged"
                else:
                    last_price = "No History"
                    price_change = 0
                    status = "New Item"
                
                comparison_results.append({
                    "Item": item_name,
                    "Last Paid Price": last_price,
                    "New Invoice Price": new_price,
                    "Difference": round(price_change, 2),
                    "Status": status
                })
            
            # --- DISPLAY RESULTS ---
            df = pd.DataFrame(comparison_results)
            
            def color_status(val):
                if val == 'Increased': return 'background-color: #ffcccc' # Red
                if val == 'Decreased': return 'background-color: #ccffcc' # Green
                if val == 'New Item': return 'background-color: #ffffcc' # Yellow
                return ''

            st.dataframe(df.style.map(color_status, subset=['Status']), use_container_width=True)
            
            # Temporarily hold the data in the app's memory
            st.session_state['pending_invoice'] = invoice_data

    except Exception as e:
        st.error(f"Something went wrong: {e}")

# --- 4. THE SAVE BUTTON (PERMANENT MEMORY) ---
if 'pending_invoice' in st.session_state:
    st.divider()
    st.warning("Review the prices above. Clicking save will update your database for future comparisons.")
    
    if st.button("💾 Save to Enterprise Database"):
        data = st.session_state['pending_invoice']
        v_name = data["Vendor_Name"].replace("/", "-").strip()
        
        with st.spinner(f"Saving {len(data['Items'])} items..."):
            for itm in data["Items"]:
                i_name = itm["Item_Name"].replace("/", "-").strip()
                n_price = float(itm["New_Price"])
                
                # Write to Firestore
                db.collection("vendor_prices").document(f"{v_name}_{i_name}").set({
                    "vendor": v_name,
                    "item": i_name,
                    "last_price": n_price
                })
                
        st.success(f"Prices for {v_name} have been updated successfully!")
        # Clear the memory so it doesn't show the button again
        del st.session_state['pending_invoice']
