import streamlit as st
import pandas as pd
import vertexai
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig
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
        
        # --- APPLIED FIX: Added Schema to prevent KeyError and JSON formatting errors ---
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
        
        model = GenerativeModel(
            'gemini-3.1-pro-preview',
            generation_config=GenerationConfig(
                response_mime_type="application/json",
                response_schema=response_schema
            )
        )
        
        prompt = """
        Read this invoice and extract the vendor name and every line item with its unit price.
        IMPORTANT: For the 'Item_Name', you MUST combine the Description and the Size so that items with the same name but different sizes are completely unique. 
        For example, output 'FOCA LIQUID LAUNDRY 240 F' and 'FOCA LIQUID LAUNDRY 128 F'.
        """
        
        with st.spinner("AI is reading the invoice and checking the database..."):
            response = model.generate_content([document_part, prompt])
            # The schema ensures the output is clean JSON, no string replacement needed
            invoice_data = json.loads(response.text)
            
            # Clean the vendor name so it doesn't have slashes
            vendor_name = invoice_data["Vendor_Name"].replace("/", "-")
            st.subheader(f"🏢 Vendor: {vendor_name}")
            
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
            
            # --- DISPLAY PREPARATION ---
            # Instead of showing the table here, we just save the raw data to memory
            st.session_state['raw_comparison'] = comparison_results
            st.session_state['pending_vendor'] = vendor_name

    except Exception as e:
        st.error(f"Something went wrong: {e}")

# --- 4. THE INTERACTIVE TABLE & SAVE BUTTON ---
# Because this is OUTSIDE the "Process" button, it won't disappear when edited!
if 'raw_comparison' in st.session_state:
    st.divider()
    st.subheader(f"🏢 Vendor: {st.session_state['pending_vendor']}")
    st.markdown("### 📝 Review and Edit")
    st.info("If a price is incorrect due to a vendor change or AI error, click the number in the 'New Invoice Price' column to fix it.")
    
    df = pd.DataFrame(st.session_state['raw_comparison'])
    
    def color_status(val):
        if val == 'Increased': return 'background-color: #ffcccc'
        if val == 'Decreased': return 'background-color: #ccffcc'
        if val == 'New Item': return 'background-color: #ffffcc'
        return ''

    # Show the editable table
    edited_df = st.data_editor(
        df.style.map(color_status, subset=['Status']), 
        use_container_width=True,
        disabled=["Item", "Last Paid Price", "Difference", "Status"], # Lock everything except new price
        hide_index=True
    )

    st.warning("Review the prices above. Clicking save will update your database for future comparisons.")
    
    if st.button("💾 Save Verified Prices to Database"):
        v_name = st.session_state['pending_vendor']
        # Grab the data directly from the edited table so your changes are saved
        items_to_save = edited_df.to_dict('records') 
        
        with st.spinner(f"Saving {len(items_to_save)} items..."):
            for row in items_to_save:
                i_name = row["Item"]
                n_price = float(row["New Invoice Price"]) 
                
                # Write to Firestore
                db.collection("vendor_prices").document(f"{v_name}_{i_name}").set({
                    "vendor": v_name,
                    "item": i_name,
                    "last_price": n_price
                })
                
        st.success(f"Prices for {v_name} have been updated successfully!")
        
        # Clear the memory so the screen resets for the next invoice
        del st.session_state['raw_comparison']
        del st.session_state['pending_vendor']
