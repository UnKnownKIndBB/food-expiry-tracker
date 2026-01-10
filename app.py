import streamlit as st
from ocr_engine import FoodExpiryDetector
from database import FoodDatabase, FoodItem
from datetime import datetime

st.set_page_config(page_title="AI Food Expiry Tracker", layout="wide")

st.title("🍲 AI Food Expiry & Waste Tracker")
st.markdown("Upload a photo of food label or add manually → never waste food again!")

# Initialize
db = FoodDatabase()
detector = FoodExpiryDetector(tesseract_cmd=r"C:\Program Files\Tesseract-OCR\tesseract.exe")

# Tabs for clean UI
tab1, tab2, tab3 = st.tabs(["📸 Add from Photo", "✍️ Manual Entry", "📊 Dashboard"])

with tab1:
    st.subheader("Take/Upload Food Label Photo")
    uploaded_file = st.file_uploader("Choose image...", type=["jpg", "jpeg", "png"])

    if uploaded_file:
        # Save temporarily
        with open("temp.jpg", "wb") as f:
            f.write(uploaded_file.getvalue())

        with st.spinner("Analyzing label..."):
            result = detector.extract_expiry_date("temp.jpg")

        if result['success']:
            st.success(f"Found expiry: **{result['date']}** ({result['days_until_expiry']} days left)")
            st.image("temp.jpg", caption="Uploaded label", width=400)
        else:
            st.error(result['error'])

with tab2:
    st.subheader("Add Item Manually")
    name = st.text_input("Item Name")
    category = st.selectbox("Category", ["dairy", "fruits", "vegetables", "other"])
    expiry = st.date_input("Expiry Date")
    if st.button("Add to Inventory"):
        item = FoodItem(
            name=name,
            category=category,
            expiry_date=datetime.combine(expiry, datetime.min.time()),
            purchase_date=datetime.now()
        )
        db.add_food_item(item)
        st.success(f"Added {name}!")

with tab3:
    st.subheader("Current Inventory")
    items = db.get_all_items()
    if items:
        st.dataframe([vars(i) for i in items])
    else:
        st.info("No items yet. Add some!")