import streamlit as st
import io
import os
import tempfile
import re
import json
import xml.etree.ElementTree as ET
import pandas as pd
import builtins # Required for mocking input

# Ensure openai_client is accessible from previous cells or re-initialize
# For running outside Colab, you'd typically manage API keys via environment variables or a config file.
# For this script, we'll assume openai_client is either passed or initialized here.

# Re-initializing OpenAI client and helper functions for script.py if not already done via imports
# (Assuming these were defined in previous cells and are available when this script is run within Colab context initially,
# or will be manually placed/imported if run completely standalone).
# For a standalone script, you'd move the definition of openai_client and the helper functions here or import them.

# Placeholder for openai_client if running truly standalone without Colab's previous cells
try:
    from google.colab import userdata
    OPENAI_API_KEY = userdata.get('OPENAI_API_KEY')
except ImportError:
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY') # For local environment variables

import openai
openai_client = None
if OPENAI_API_KEY:
    try:
        openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
    except Exception as e:
        st.error(f"Error initializing OpenAI client in script.py: {e}")
else:
    st.warning("OPENAI_API_KEY not found. Please set it as a Colab secret or environment variable.")

# --- Helper functions (Assuming they are already defined in the notebook's global scope or imported) ---
# For a fully standalone script, you would include the definitions of:
# parse_value_unit, get_numerical_value, extract_text_from_pdf, extract_information_openai,
# process_battery_parameters, generate_characterization_xml_file, analyze_csv_and_generate_fast_charge_xml_file
# directly in this script. For now, we assume they are accessible.

# For demonstration purposes, I'll include the function definitions here for a truly standalone script.
# In your Colab environment, if these are already defined in earlier cells, you might not strictly need them here.

def parse_value_unit(param_str):
    """Parses a string like '1750 mA' into a numeric value and a unit."""
    match = re.match(r'([\d.]+)\s*([a-zA-Z]+(?:h|A|V|C)?)', str(param_str))
    if match:
        value = float(match.group(1))
        unit = match.group(2).strip()
        return value, unit
    return None, None

def get_numerical_value(param_string):
    """Extracts the numerical value from a string like '2.6 Ah'."""
    try:
        return float(param_string.split(' ')[0])
    except (ValueError, AttributeError):
        return None

def extract_text_from_pdf(pdf_path):
    """Extracts all text from a PDF file."""
    text = ""
    try:
        import pypdf # Import locally to avoid dependency issues if not installed
        with open(pdf_path, 'rb') as f:
            reader = pypdf.PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() + "\n"
    except ImportError:
        st.error("pypdf library not found. Please install it: pip install pypdf")
        return None
    except Exception as e:
        st.error(f"Error reading PDF: {e}")
        return None
    return text

def extract_information_openai(text, client):
    """Extracts specific information from the PDF text using OpenAI API."""
    if not client:
        st.error("OpenAI client not initialized. Cannot extract information.")
        return {
            "Maximum charging current": "N/A",
            "Maximum discharging current": "N/A",
            "Maximum charging voltage": "N/A",
            "Capacity": "N/A"
        }

    prompt_message = f"""Extract the following battery parameters from the provided text in JSON format, ignoring tolerance information. If there are conflicting charging limit voltages, return the lowest one. If there is tolerance information, do not return the tolerance:\n- Maximum charging current\n- Maximum discharging current\n- Maximum charging voltage\n- Capacity\n\nIf a parameter is not found, its value should be \"N/A\".\nThe JSON output should strictly follow this structure:\n{{\n  \"Maximum charging current\": \"value\",\n  \"Maximum discharging current\": \"value\",\n  \"Maximum charging voltage\": \"value\",\n  \"Capacity\": \"value\"\n}}\n\nText:\n{text}\n"""
    try:
        st.info("Sending request to OpenAI API...")
        response = client.chat.completions.create(
            #model="gpt-3.5-turbo",
            model="gpt-5.4-nano",
            messages=[
                {"role": "system", "content": "You are an expert at extracting structured information from text and outputting valid JSON."},
                {"role": "user", "content": prompt_message}
            ],
            response_format={"type": "json_object"}
        )

        extracted_data = json.loads(response.choices[0].message.content)
        return extracted_data
    except Exception as e:
        st.error(f"Error extracting information with OpenAI: {e}")
        return {
            "Maximum charging current": "N/A",
            "Maximum discharging current": "N/A",
            "Maximum charging voltage": "N/A",
            "Capacity": "N/A"
        }

def process_battery_parameters(pdf_path, openai_client):
    """Extracts battery parameters from PDF, uses OpenAI for information extraction,
    and normalizes the extracted data.

    Args:
        pdf_path (str): Path to the PDF datasheet.
        openai_client (openai.OpenAI): Initialized OpenAI client.

    Returns:
        dict: Normalized battery parameters.
    """

    st.info(f"Extracting text from {pdf_path}...")
    pdf_text = extract_text_from_pdf(pdf_path)

    if not pdf_text:
        return None

    st.info("Extracting specific information using OpenAI...")
    extracted_data = extract_information_openai(pdf_text, openai_client)

    if not extracted_data:
        return None

    # --- Normalization logic ---
    normalized_data = {}

    capacity_str = extracted_data.get('Capacity')
    normalized_capacity_value = None
    
    #st.info(f"Capacity normalization beginning: {capacity_str}")

    if capacity_str and capacity_str != 'N/A':
        value, unit = parse_value_unit(capacity_str)
        #st.info(f"Value = {value}, unit = {unit}")
        if value is not None and unit is not None:
            if unit.lower() == 'mah':
                normalized_capacity_value = value / 1000
                normalized_capacity_unit = 'Ah'
                #st.info(f"Capacity normalization: {normalized_capacity_value} {normalized_capacity_unit}")
            elif unit.lower() == 'ah':
                normalized_capacity_value = value
                normalized_capacity_unit = 'Ah'
            else:
                normalized_capacity_value = value
                normalized_capacity_unit = unit
                st.warning(f"Warning: Unexpected unit '{unit}' for Capacity. Expected 'mAh' or 'Ah'. Keeping original value.")
            normalized_data['Capacity'] = f"{normalized_capacity_value} {normalized_capacity_unit}"
        else:
            normalized_data['Capacity'] = capacity_str
    else:
        normalized_data['Capacity'] = 'N/A'

    current_keys = ['Maximum charging current', 'Maximum discharging current']
    for key in current_keys:
        current_str = extracted_data.get(key)
        if current_str and current_str != 'N/A':
            value, unit = parse_value_unit(current_str)
            if value is not None and unit is not None:
                if unit.lower() == 'c':
                    if normalized_capacity_value is not None and normalized_data['Capacity'].endswith('Ah'):
                        current_in_amps = value * normalized_capacity_value
                        normalized_data[key] = f"{current_in_amps:.2f} A"
                    else:
                        st.warning(f"Warning: Cannot normalize '{key}' with 'C' unit. Capacity '{normalized_data.get('Capacity', 'N/A')}' is not available or not in 'Ah'. Keeping original value.")
                        normalized_data[key] = current_str
                elif unit.lower() == 'ma':
                    normalized_data[key] = f"{value / 1000:.2f} A"
                elif unit.lower() == 'a':
                    normalized_data[key] = f"{value:.2f} A"
                else:
                    normalized_data[key] = current_str
                    st.warning(f"Warning: Unexpected unit '{unit}' for '{key}'. Expected 'C', 'mA', or 'A'. Keeping original value.")
            else:
                normalized_data[key] = current_str
        else:
            normalized_data[key] = 'N/A'

    voltage_key = 'Maximum charging voltage'
    voltage_str = extracted_data.get(voltage_key)
    if voltage_str and voltage_str != 'N/A':
        value, unit = parse_value_unit(voltage_str)
        if value is not None and unit is not None:
            if unit.lower() == 'mv':
                normalized_data[voltage_key] = f"{value / 1000:.2f} V"
            elif unit.lower() == 'v':
                normalized_data[voltage_key] = f"{value:.2f} V"
            else:
                normalized_data[voltage_key] = voltage_str
                st.warning(f"Warning: Unexpected unit '{unit}' for '{voltage_key}'. Expected 'mV' or 'V'. Keeping original value.")
        else:
            normalized_data[voltage_key] = voltage_str
    else:
        normalized_data[voltage_key] = 'N/A'

    return normalized_data

def generate_characterization_xml_file(normalized_data, nominal_capacity_ah, nominal_voltage, input_xml_template_path, output_xml_filename_char):
    """Generates the characterization XML file based on normalized battery parameters and user inputs.

    Args:
        normalized_data (dict): Dictionary of normalized battery parameters.
        nominal_capacity_ah (float): Nominal battery capacity in Ah.
        nominal_voltage (float): Nominal battery voltage in V.
        input_xml_template_path (str): Path to the XML template for characterization.
        output_xml_filename_char (str): Desired output filename for the characterization XML.

    Returns:
        tuple: Calculated parameters (first_discharging_current, charging_current, cut_off_current,
               cut_off_voltage, max_charging_voltage_extracted) for use in subsequent steps.
    """
    try:
        tree = ET.parse(input_xml_template_path)
        root = tree.getroot()
    except FileNotFoundError:
        st.error(f"Error: Input XML file '{input_xml_template_path}' not found.")
        return
    except ET.ParseError as e:
        st.error(f"Error parsing XML file '{input_xml_template_path}': {e}")
        return

    def update_xml_parameter(root_element, step_id, parameter_tag_name, attribute_name, new_value):
        updated = False
        xpath_expression = f".//Step_Info/Step{step_id}[@Step_ID='{step_id}']/Limit/Main/{parameter_tag_name}"
        param_elem = root_element.find(xpath_expression)

        if param_elem is not None:
            param_elem.set(attribute_name, str(new_value))
            st.info(f"Updated Step_ID='{step_id}' - {parameter_tag_name} attribute '{attribute_name}' to {new_value}")
            updated = True
        if not updated:
            st.warning(f"Warning: Could not find '{parameter_tag_name}' for Step_ID='{step_id}' (XPath: {xpath_expression}) to set attribute '{attribute_name}'.")
        return updated

    max_discharging_current = get_numerical_value(normalized_data.get('Maximum discharging current'))
    battery_capacity = get_numerical_value(normalized_data.get('Capacity'))
    max_charging_current_extracted = get_numerical_value(normalized_data.get('Maximum charging current'))
    max_charging_voltage_extracted = get_numerical_value(normalized_data.get('Maximum charging voltage'))

    if None in [max_discharging_current, battery_capacity, max_charging_current_extracted, max_charging_voltage_extracted]:
        st.error("Error: Could not extract all required numerical battery parameters for XML generation.")
        return

    # The target_soc_input is now coming from Streamlit directly, not via builtins.input
    # We need to get it from st.session_state if it was set, or prompt if this function is called outside Streamlit context
    # For the Streamlit script, we assume target_soc_input is available as an argument or from session_state
    # For this file generation, the original Streamlit code already handles passing target_soc_input from st.number_input

    # We are mocking builtins.input for the case when this function is called from the Streamlit app.
    # However, if this script were run standalone, and this function was defined directly here,
    # it would need `target_soc_input` passed as an argument. The original notebook code had `input()` here.
    # For the `script.py` I'm creating, I'll assume the Streamlit app passes it, or, if run standalone,
    # a default or mocked value would be provided.

    # To make this script runnable standalone and from the Streamlit app without modification:
    # We need to assume target_soc_input is available from the calling context (Streamlit in this case).
    # The mock_input_soc function handles the original `input()` call within this function.
    # We will pass a dummy target_soc_input to this function and let the mock handle the actual value.

    # This part of the code needs to be careful because of how the original `generate_characterization_xml_file`
    # is structured with an internal `input()` call. The Streamlit app patched `builtins.input`.
    # If this `script.py` is run standalone, this patch won't be active unless applied.
    # For `script.py` we should ensure that the function *can* be called with a target_soc if needed.
    # Or ensure the `input` mock is active in main.

    # For the purpose of writing script.py, I will assume the prompt means the Streamlit `target_soc_input`
    # from `st.number_input` should be used. The mocking mechanism is part of the Streamlit `main` function.

    # Let's ensure target_soc_input is available here, as it was in the Streamlit app's context.
    # The existing Streamlit code already handles `target_soc_input` being set by `st.number_input`.
    # The function `generate_characterization_xml_file` is defined to internally ask for it via `input()`.
    # So the mock for `input()` is crucial.

    # Assuming `target_soc_input` is handled by the `builtins.input` mock set up in the `main` Streamlit function.
    # The original function signature for `generate_characterization_xml_file` in `fdde173f` does not include `target_soc_input`.
    # The `builtins.input` mock in the Streamlit app is what provides it.

    # The original notebook had the `input()` call *inside* this function.
    # To make `script.py` work, we need that `input()` call, and the Streamlit app's mock will handle it.

    # The target_soc_input variable below is a *local* variable in Streamlit's `main()`.
    # So, `generate_characterization_xml_file` *must* obtain `target_soc_input` through `input()`.
    # The previous response correctly implemented the `builtins.input` mock for this.

    # The calculations use `target_soc`. The `input()` call inside `generate_characterization_xml_file` directly populates `target_soc_input`.
    # So we don't need to pass it explicitly to the function in its current form.
    # We just need to ensure the `builtins.input` mock is in place when this function is called from Streamlit.

    # Calculate characterization test parameters
    first_discharging_current = min(0.75 * max_discharging_current, 1 * battery_capacity)
    second_discharging_current = 0.2 * battery_capacity
    #charging_current = 0.75 * max_charging_current_extracted
    charging_current = min(0.75 * max_charging_current_extracted, 1 * battery_capacity)
    
    if (first_discharging_current > 6.0) or (charging_current > 6.0):
        st.error("Current above Neware limit.")

    # Prompt for target SoC (this will be intercepted by the mock in Streamlit)
    target_soc_input_for_func = 50.0 # Default value if mock is not active or for standalone test
    try:
        # This call will be intercepted by the mock_input_soc function in Streamlit.
        # If running standalone, it will actually prompt.
        target_soc_input_for_func = float(builtins.input("Please enter the target SoC (0-100%): "))
        if not (0 <= target_soc_input_for_func <= 100):
            st.error("SoC must be between 0 and 100.")
            return None
    except ValueError:
        st.error("Invalid input for SoC. Please enter a numerical value.")
        return None
    
    target_soc = target_soc_input_for_func / 100.0
    target_capacity = battery_capacity * target_soc

    if max_charging_voltage_extracted < 5.0:
        cut_off_voltage = 3.0
    else:
        cut_off_voltage = 6.0

    cut_off_current = 0.1 * charging_current

    st.subheader("Calculated Characterization Test Parameters")
    st.write(f"Target SoC: {target_soc_input_for_func:.1f} %")
    st.write(f"First discharging current: {first_discharging_current:.2f} A")
    st.write(f"Second discharging current: {second_discharging_current:.2f} A")
    st.write(f"Charging current: {charging_current:.2f} A")
    st.write(f"Target capacity: {target_capacity:.2f} Ah")
    st.write(f"Cut-off voltage: {cut_off_voltage:.1f} V")
    st.write(f"Cut-off current: {cut_off_current:.2f} A")

    update_xml_parameter(root, 1, 'Curr', 'Value', round(first_discharging_current * 1000, 2))
    update_xml_parameter(root, 1, 'Stop_Volt', 'Value', round(cut_off_voltage * 10000, 2))
    update_xml_parameter(root, 2, 'Curr', 'Value', round(second_discharging_current * 1000, 2))
    update_xml_parameter(root, 2, 'Stop_Volt', 'Value', round(cut_off_voltage * 10000, 2))
    update_xml_parameter(root, 3, 'Curr', 'Value', round(charging_current * 1000, 2))
    update_xml_parameter(root, 3, 'Volt', 'Value', round(max_charging_voltage_extracted * 10000, 2))
    update_xml_parameter(root, 3, 'Cap', 'Value', round(target_capacity * 3600000, 2))
    update_xml_parameter(root, 3, 'Stop_Curr', 'Value', round(cut_off_current * 1000, 2))
    update_xml_parameter(root, 5, 'Curr', 'Value', round(charging_current * 1000, 2))
    update_xml_parameter(root, 5, 'Volt', 'Value', round(max_charging_voltage_extracted * 10000, 2))
    update_xml_parameter(root, 5, 'Stop_Curr', 'Value', round(cut_off_current * 1000, 2))
    update_xml_parameter(root, 7, 'Curr', 'Value', round(first_discharging_current * 1000, 2))
    update_xml_parameter(root, 7, 'Stop_Volt', 'Value', round(cut_off_voltage * 10000, 2))

    try:
        ET.indent(tree, space="  ", level=0)
        tree.write(output_xml_filename_char, encoding='utf-8', xml_declaration=True)
        st.success(f"Successfully generated '{output_xml_filename_char}' with updated parameters.")
    except Exception as e:
        st.error(f"Error writing XML file '{output_xml_filename_char}': {e}")
        return

    return first_discharging_current, charging_current, cut_off_current, cut_off_voltage, max_charging_voltage_extracted

def analyze_csv_and_generate_fast_charge_xml_file(csv_file_path, input_xml_template_path_fast_charge, output_xml_filename_fast_charge, calculated_params):
    """Analyzes the characterization CSV data and generates the fast charge XML file.

    Args:
        csv_file_path (str): Path to the characterization result CSV file.
        input_xml_template_path_fast_charge (str): Path to the XML template for fast charge.
        output_xml_filename_fast_charge (str): Desired output filename for the fast charge XML.
        calculated_params (tuple): Tuple containing (first_discharging_current, charging_current,
                                   cut_off_current, cut_off_voltage, max_charging_voltage_extracted)
                                   from the characterization XML generation step.
    """
    first_discharging_current, charging_current, cut_off_current, cut_off_voltage, max_charging_voltage_extracted = calculated_params

    try:
        df_caracterization = pd.read_csv(csv_file_path)
        st.info(f"Successfully loaded {csv_file_path}")
    except FileNotFoundError:
        st.error(f"Error: CSV file '{csv_file_path}' not found.")
        return
    except Exception as e:
        st.error(f"Error loading CSV file: {e}")
        return

    cc_dchg_df = df_caracterization[df_caracterization['Step Type'] == 'CC DChg']
    min_caracterization_voltage = None
    if not cc_dchg_df.empty:
        min_caracterization_voltage = cc_dchg_df['Voltage(V)'].iloc[-1]
        st.write(f"Minimum caracterization voltage (from 'CC DChg' last value): {min_caracterization_voltage} V")
    else:
        st.warning("No 'CC DChg' test step found in the CSV.")

    cccv_chg_df = df_caracterization[df_caracterization['Step Type'] == 'CCCV Chg']
    max_caracterization_voltage = None
    if not cccv_chg_df.empty:
        max_caracterization_voltage = cccv_chg_df['Voltage(V)'].iloc[-1]
        st.write(f"Maximum caracterization voltage (from 'CCCV Chg' last value): {max_caracterization_voltage} V")
    else:
        st.warning("No 'CCCV Chg' test step found in the CSV.")

    threshold_voltage = None
    rest_indices = df_caracterization[df_caracterization['Step Type'] == 'Rest'].index

    if rest_indices.empty:
        st.warning("No 'Rest' test step found in the CSV.")
    else:
        diffs = pd.Series(rest_indices).diff()
        break_point_mask = diffs > 1

        if break_point_mask.any():
            position_of_break_in_rest_indices = break_point_mask.idxmax()
            last_index_of_first_rest_block = rest_indices[position_of_break_in_rest_indices - 1]
            threshold_voltage = df_caracterization.loc[last_index_of_first_rest_block, 'Voltage(V)']
        else:
            threshold_voltage = df_caracterization.loc[rest_indices[-1], 'Voltage(V)']

        if threshold_voltage is not None:
            st.write(f"Threshold voltage (from last value of the first 'Rest' test): {threshold_voltage} V")
        else:
            st.warning("Could not determine threshold voltage from the first 'Rest' test.")

    try:
        tree_fast_charge = ET.parse(input_xml_template_path_fast_charge)
        root_fast_charge = tree_fast_charge.getroot()
    except FileNotFoundError:
        st.error(f"Error: Input XML file '{input_xml_template_path_fast_charge}' not found.")
        return
    except ET.ParseError as e:
        st.error(f"Error parsing XML file '{input_xml_template_path_fast_charge}': {e}")
        return

    def update_fast_charge_xml_parameter(root_element, step_id, parameter_tag_name, attribute_name, new_value):
        updated = False
        step_id_str = str(step_id)
        step_element_path = f".//Step_Info/Step{step_id_str}[@Step_ID='{step_id_str}']"
        step_elem = root_element.find(step_element_path)

        if step_elem is not None:
            xpath_main_relative = f"Limit/Main/{parameter_tag_name}"
            param_elem = step_elem.find(xpath_main_relative)

            if param_elem is not None:
                param_elem.set(attribute_name, str(round(new_value, 4)))
                st.info(f"Updated Step_ID='{step_id_str}' - {parameter_tag_name} attribute '{attribute_name}' to {round(new_value, 4)}")
                updated = True
            else:
                xpath_other_relative = f"Limit/Other/{parameter_tag_name}"
                param_elem = step_elem.find(xpath_other_relative)
                if param_elem is not None:
                    param_elem.set(attribute_name, str(round(new_value, 4)))
                    st.info(f"Updated Step_ID='{step_id_str}' - {parameter_tag_name} attribute '{attribute_name}' to {round(new_value, 4)}")
                    updated = True

        if not updated:
            st.warning(f"Warning: Could not find '{parameter_tag_name}' for Step_ID='{step_id_str}' to set attribute '{attribute_name}'.")
        return updated

    if threshold_voltage is None or min_caracterization_voltage is None or max_caracterization_voltage is None:
        st.error("Error: Missing one or more critical voltages from CSV analysis. Cannot generate Fast Charge XML.")
        return
        
    if (threshold_voltage > max_charging_voltage_extracted) or (min_caracterization_voltage > max_caracterization_voltage) or (max_caracterization_voltage > max_charging_voltage_extracted):
        st.error("Error: Caracterization voltages above the maximum battery voltage or minimum voltage higher than the maximum voltage. Cannot generate Fast Charge XML.")
        return

    update_fast_charge_xml_parameter(root_fast_charge, 2, 'Cnd1', 'Value', threshold_voltage * 10000)
    update_fast_charge_xml_parameter(root_fast_charge, 3, 'Curr', 'Value', first_discharging_current * 1000)
    update_fast_charge_xml_parameter(root_fast_charge, 3, 'Stop_Volt', 'Value', min_caracterization_voltage * 10000)
    update_fast_charge_xml_parameter(root_fast_charge, 5, 'Curr', 'Value', charging_current * 1000)
    update_fast_charge_xml_parameter(root_fast_charge, 5, 'Volt', 'Value', max_charging_voltage_extracted * 10000)
    update_fast_charge_xml_parameter(root_fast_charge, 5, 'Stop_Curr', 'Value', cut_off_current * 1000)
    update_fast_charge_xml_parameter(root_fast_charge, 5, 'Cnd1', 'Value', max_caracterization_voltage * 10000)

    try:
        ET.indent(tree_fast_charge, space="  ", level=0)
        tree_fast_charge.write(output_xml_filename_fast_charge, encoding='utf-8', xml_declaration=True)
        st.success(f"Successfully generated '{output_xml_filename_fast_charge}' with updated parameters.")
    except Exception as e:
        st.error(f"Error writing XML file '{output_xml_filename_fast_charge}': {e}")


st.set_page_config(layout="wide", page_title="BaterIA: Parameter Extractor & XML Generator")

def main():
    st.title("🔋 BaterIA: Datasheet Analyzer & XML Generator for Neware")
    st.write("Upload your battery datasheet PDF and characterization CSV to generate XML files.")

    # --- 1. PDF Upload and Parameter Extraction ---
    st.header("Step 1: Upload Datasheet PDF and Extract Parameters")
    uploaded_pdf_file = st.file_uploader("Upload Battery Datasheet (PDF)", type=["pdf"])

    normalized_parameters = None
    if uploaded_pdf_file is not None:
        with st.spinner("Processing PDF and extracting information with OpenAI..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
                tmp_pdf.write(uploaded_pdf_file.read())
                temp_pdf_path = tmp_pdf.name

            try:
                global openai_client # Ensure openai_client is accessible
                if openai_client is None:
                    st.error("OpenAI client not initialized. Please set OPENAI_API_KEY.")
                    os.unlink(temp_pdf_path)
                    return

                normalized_parameters = process_battery_parameters(temp_pdf_path, openai_client)
                if normalized_parameters and all(value != "N/A" for value in normalized_parameters.values()):
                    st.success("Battery parameters extracted and normalized successfully!")
                    with st.expander("View Normalized Battery Parameters"):
                        for key, value in normalized_parameters.items():
                            st.write(f"**{key}**: {value}")
                else:
                    st.error("Failed to extract all battery parameters from the PDF. Some values might be 'N/A'. Please check the datasheet content.")
            except Exception as e:
                st.error(f"An error occurred during PDF processing: {e}")
            finally:
                os.unlink(temp_pdf_path)

    if normalized_parameters:
        # --- 2. User Inputs and Sanity Checks ---
        st.header("Step 2: Enter Nominal Values and Perform Sanity Checks")
        st.write("Please provide the nominal capacity and voltage for sanity checks.")

        col1, col2 = st.columns(2)
        with col1:
            nominal_capacity_mah = st.number_input("Nominal Capacity (mAh):", min_value=1.0, value=2600.0, step=100.0, key="nominal_cap_input")
        with col2:
            nominal_voltage = st.number_input("Nominal Voltage (V):", min_value=0.1, value=3.6, step=0.1, key="nominal_volt_input")

        if st.button("Perform Sanity Checks", key="sanity_check_button"):
            st.info(f"Nominal capacity (converted to Ah): {nominal_capacity_mah / 1000:.2f} Ah")

            nominal_capacity_ah = nominal_capacity_mah / 1000

            battery_capacity = get_numerical_value(normalized_parameters.get('Capacity'))
            if battery_capacity is not None:
                if not (0.9 * nominal_capacity_ah <= battery_capacity <= 1.0 * nominal_capacity_ah):
                    st.warning(f"Warning: Extracted capacity ({battery_capacity:.2f} Ah) is not within 0.9-1.0 of nominal capacity ({nominal_capacity_ah:.2f} Ah).")
                else:
                    st.success(f"Check passed: Extracted capacity ({battery_capacity:.2f} Ah) is within 0.9-1.0 of nominal capacity ({nominal_capacity_ah:.2f} Ah).")
            else:
                st.warning("Warning: 'Capacity' not found in normalized data. Cannot perform capacity range check.")

            max_charging_voltage_extracted = get_numerical_value(normalized_parameters.get('Maximum charging voltage'))
            if max_charging_voltage_extracted is not None:
                if not (max_charging_voltage_extracted < nominal_voltage * 1.25):
                    st.warning(f"Warning: Maximum charging voltage ({max_charging_voltage_extracted:.2f} V) is not less than 1.25 times nominal voltage ({nominal_voltage * 1.25:.2f} V).")
                else:
                    st.success(f"Check passed: Maximum charging voltage ({max_charging_voltage_extracted:.2f} V) is less than 1.25 times nominal voltage ({nominal_voltage * 1.25:.2f} V).")
            else:
                st.warning("Warning: 'Maximum charging voltage' not found in normalized data. Cannot perform charging voltage check.")

            st.session_state['nominal_capacity_ah'] = nominal_capacity_ah
            st.session_state['nominal_voltage'] = nominal_voltage

        if 'nominal_capacity_ah' in st.session_state and 'nominal_voltage' in st.session_state:
            # --- 3. Generate Characterization XML ---
            st.header("Step 3: Generate Characterization XML")
            target_soc_input = st.number_input("Target SoC (0-100%):", min_value=0.0, max_value=100.0, value=50.0, step=5.0, key="target_soc_input")
            output_char_xml_name = st.text_input("Filename for Characterization XML:", value="MP35P_caract.xml", key="char_xml_name_input")

            if st.button("Generate Characterization XML", key="generate_char_xml_button"):
                st.info("Generating characterization XML file...")

                characterization_xml_template = "Caracterizador_example.xml" # Assuming templates are in same dir for standalone script

                if not os.path.exists(characterization_xml_template):
                    st.error(f"Characterization XML template not found at {characterization_xml_template}. Please ensure it's uploaded or present in the same directory as script.py.")
                else:
                    try:
                        original_input = builtins.input

                        def mock_input_soc(prompt):
                            if "target SoC" in prompt:
                                st.session_state['_temp_soc_prompt'] = prompt
                                return str(target_soc_input)
                            return original_input(prompt)

                        builtins.input = mock_input_soc

                        calculated_char_params = None
                        try:
                            calculated_char_params = generate_characterization_xml_file(
                                normalized_parameters,
                                st.session_state['nominal_capacity_ah'],
                                st.session_state['nominal_voltage'],
                                characterization_xml_template,
                                output_char_xml_name
                            )
                        finally:
                            builtins.input = original_input

                        if calculated_char_params:
                            if os.path.exists(output_char_xml_name):
                                with open(output_char_xml_name, "rb") as f:
                                    st.download_button(
                                        label=f"Download {output_char_xml_name}",
                                        data=f.read(),
                                        file_name=output_char_xml_name,
                                        mime="application/xml",
                                        key="download_char_xml_button"
                                    )
                            else:
                                st.error("Generated XML file not found on disk. Check logs for errors.")
                            st.session_state['calculated_char_params'] = calculated_char_params
                        else:
                            st.error("Failed to generate Characterization XML. Check logs for details.")
                    except Exception as e:
                        st.error(f"An error occurred during Characterization XML generation: {e}")

            if 'calculated_char_params' in st.session_state:
                # --- 4. CSV Upload and Fast Charge XML Generation ---
                st.header("Step 4: Upload Characterization CSV and Generate Fast Charge XML")
                uploaded_csv_file = st.file_uploader("Upload Characterization Result CSV (e.g., from generated characterization test)", type=["csv"])
                output_fast_charge_xml_name = st.text_input("Filename for Fast Charge XML:", value="MP35P_fast_charge.xml", key="fast_charge_xml_name_input")

                if uploaded_csv_file is not None and st.button("Generate Fast Charge XML", key="generate_fast_charge_xml_button"):
                    st.info("Analyzing CSV and generating fast charge XML file...")

                    with st.spinner("Processing CSV and generating Fast Charge XML..."):
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp_csv:
                            tmp_csv.write(uploaded_csv_file.read())
                            temp_csv_path = tmp_csv.name

                        fast_charge_xml_template = "FastCharge_example.xml" # Assuming templates are in same dir

                        if not os.path.exists(fast_charge_xml_template):
                            st.error(f"Fast Charge XML template not found at {fast_charge_xml_template}. Please ensure it's uploaded or present in the same directory as script.py.")
                            os.unlink(temp_csv_path)
                        else:
                            try:
                                analyze_csv_and_generate_fast_charge_xml_file(
                                    temp_csv_path,
                                    fast_charge_xml_template,
                                    output_fast_charge_xml_name,
                                    st.session_state['calculated_char_params']
                                )
                                if os.path.exists(output_fast_charge_xml_name):
                                    with open(output_fast_charge_xml_name, "rb") as f:
                                        st.download_button(
                                            label=f"Download {output_fast_charge_xml_name}",
                                            data=f.read(),
                                            file_name=output_fast_charge_xml_name,
                                            mime="application/xml",
                                            key="download_fast_charge_xml_button"
                                        )
                                else:
                                    st.error("Generated XML file not found on disk. Check logs for errors.")
                            except Exception as e:
                                st.error(f"An error occurred during Fast Charge XML generation: {e}")
                            finally:
                                os.unlink(temp_csv_path)


if __name__ == "__main__":
    main()
