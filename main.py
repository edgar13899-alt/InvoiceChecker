import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import os

# Set up the look of the web app
st.set_page_config(page_title="Invoice Price Checker", layout="wide")
st.title("🧾 Invoice Price Checker")
st.markdown("Upload your master price list (Excel) and a recent invoice to detect price changes.")

# API Key Input
api_key = st.text_input("Enter your Google AI Studio API Key:", type="password")

col1, col2 = st.columns(2)

with col1:
    excel_file = st.file_uploader("1. Upload Excel Price List (.xlsx)", type=["xlsx"])

with col2:
    invoice_file = st.file_uploader("2. Upload Invoice Document", type=["png", "jpg", "jpeg", "pdf"])

if st.button("Compare Prices") and excel_file and invoice_file and api_key:
    try:
        # Configure Google AI Studio API
        genai.configure(api_key=api_key)
        
        # Load Excel data into a DataFrame
        df = pd.read_excel(excel_file)
        
        # Convert Excel data to a text format the AI can easily read
        price_list_text = df.to_csv(index=False)
        
        # Save the uploaded invoice temporarily so Gemini can process it
        temp_file_path = f"temp_{invoice_file.name}"
        with open(temp_file_path, "wb") as f:
            f.write(invoice_file.getbuffer())
        
        # Upload the file to Google's servers for processing
        uploaded_gemini_file = genai.upload_file(temp_file_path)
        
        # Use Gemini 1.5 Pro for high-accuracy document parsing
        model = genai.GenerativeModel('gemini-1.5-pro')
        
        # Give the AI its instructions
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
        
        with st.spinner("AI is analyzing the invoice and comparing prices..."):
            # Send the image/PDF and the prompt to Gemini
            response = model.generate_content([uploaded_gemini_file, prompt])
            
            # Clean up the AI's response to extract just the JSON data
            result_text = response.text.replace('```json', '').replace('```', '').strip()
            result_data = json.loads(result_text)
            
            # Convert the JSON data into a neat table
            result_df = pd.DataFrame(result_data)
            
            st.success("Comparison Complete!")
            
            # Create a function to highlight price increases in red for quick visibility
            def highlight_increases(val):
                color = '#ff9999' if val == 'Increased' else ''
                return f'background-color: {color}'
            
            # Display the interactive table
            st.dataframe(result_df.style.map(highlight_increases, subset=['Status']), use_container_width=True)
            
        # Clean up the temporary file
        os.remove(temp_file_path)

    except Exception as e:
        st.error(f"An error occurred: {e}")