import streamlit as st

st.title("House Information Form")

house_no = st.text_input("House Number")
is_rented = st.checkbox("Is the house on rent?")

if is_rented:
    st.subheader("Lessee Details")
    lessee_name = st.text_input("Lessee Name")
    lessee_contact = st.text_input("Lessee Contact Number")
    lessee_cnic = st.text_input("Lessee CNIC")

# Manual submit button
if st.button("Submit"):
    st.success("Form submitted successfully!")
    st.write(f"House No: {house_no}")
    if is_rented:
        st.write(f"Lessee Name: {lessee_name}")
        st.write(f"Lessee Contact: {lessee_contact}")
        st.write(f"Lessee CNIC: {lessee_cnic}")
