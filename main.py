import streamlit as st
import pandas as pd
import vertexai
from vertexai.generative_models import GenerativeModel, Part
from google.oauth2 import service_account
import json
import os

# Set up the look of the web app
st.set_page_config(page_title="Invoice Price Checker", layout="wide")
st.title("🧾 Invoice Price Checker (Enterprise Edition)")
st.markdown("Powered by Google Cloud Vertex AI and Gemini 3")

col1, col2 = st.columns(2)

with col1:
    excel_file = st.file_uploader("1. Upload Excel Price List (.xlsx)", type=["xlsx"])

with col2:
    invoice_file = st.file_uploader("2. Upload Invoice Document", type=["png", "jpg", "jpeg", "pdf"])

if st.button("Compare Prices") and excel_file and invoice_file:
    try:
        # 1. Unpack the JSON key using the apostrophe trick
        key_dict = json.loads(st.secrets["GCP_KEY"])
        credentials = service_account.Credentials.from_service_account_info(key_dict)
        
        # 2. Connect to the Enterprise Highway
        project_id = st.secrets["GCP_PROJECT"]
        vertexai.init(project=project_id, location="us-central1", credentials=credentials)
        
        # 3. Load Excel data
        df = pd.read_excel(excel_file)
        price_list_text = df.to_csv(index=False)
        
        # 4. Read the uploaded invoice directly from memory
        document_part = Part.from_data(data=invoice_file.getvalue(), mime_type=invoice_file.type)
        
        # 5. Initialize Gemini 3 
        model = GenerativeModel('gemini-3.0-pro')
        
        prompt = f"""
        You are an expert accountant and data analyst. 
        I am providing you with a Master Price List (in CSV format) and an uploaded Invoice document.
        
        Master Price List:
        {price_list_text}
        
        Task:
        1. Extract the line items and their unit prices from the attached Invoice.
        2. Match each extracted item from the invoice to the most likely corresponding item in the Master Price List.
        3. Compare the 'Invoice Unit Price' to the 'Master Price'.
        4. Return ONLY a valid JSON array of objects with the following exact keys:
           - "Invoice_Item_Name": The name exactly as it appears on the invoice.
           - "Matched_Master_Item": The matched name from the master price list.
           - "Invoice_Price": The unit price on the invoice (number only).
           - "Master_Price": The unit price from the master list (number only).
           - "Price_Change": The difference (Invoice_Price minus Master_Price).
           - "Status": Use ONLY "Increased", "Decreased", or "Unchanged".
        """
        
        with st.spinner("Enterprise AI is analyzing the invoice..."):
            response = model.generate_content([document_part, prompt])
            
            result_text = response.text.replace('```json', '').replace('```', '').strip()
            result_data = json.loads(result_text)
            result_df = pd.DataFrame(result_data)
            
            st.success("Comparison Complete!")
            
            def highlight_increases(val):
                color = '#ff9999' if val == 'Increased' else ''
                return f'background-color: {color}'
            
            st.dataframe(result_df.style.map(highlight_increases, subset=['Status']), use_container_width=True)

    except Exception as e:
        st.error(f"An error occurred: {e}")
