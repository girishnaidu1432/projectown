import os
import streamlit as st
from google.cloud import bigquery
from google.oauth2 import service_account
from googleapiclient.discovery import build
import openai
from langchain.document_loaders import WebBaseLoader, WikipediaLoader
from Bio import Entrez

st.markdown(f"""
     
                  <style>
            .stApp {{
                    background-image:url("https://e0.pxfuel.com/wallpapers/986/360/desktop-wallpaper-background-color-4851-background-color-theme-colorful-brown-color.jpg");
                    background-attachment: fixed;
                    background-size: cover;
            }}
         </style>
         """, unsafe_allow_html=True)
 

# Sidebar for configuration inputs
st.sidebar.title("Configuration")

# User input for API keys and credentials
GOOGLE_API_KEY = st.sidebar.text_input("Enter your GOOGLE API Key:")
SEARCH_ENGINE_ID = st.sidebar.text_input("Enter your Search Engine ID:")
OPENAI_API_KEY = st.sidebar.text_input("Enter your OpenAI API Key:")
uploaded_file = st.sidebar.file_uploader("Upload your BigQuery Credentials JSON file", type="json")

# Load service account credentials if a file is uploaded
if uploaded_file is not None:
    credentials = service_account.Credentials.from_service_account_file(uploaded_file.name)
else:
    st.sidebar.warning("Please upload your BigQuery Credentials JSON file.")

# Initialize OpenAI with the API key
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY
else:
    st.sidebar.warning("Please enter your OpenAI API Key.")

# Initialize BigQuery client
if uploaded_file is not None:
    bq_client = bigquery.Client(credentials=credentials)

# Sidebar for BigQuery table identifiers
project_id = st.sidebar.text_input("Enter your Google Cloud Project ID:")
dataset_id = st.sidebar.text_input("Enter your BigQuery Dataset ID:")
table_id = st.sidebar.text_input("Enter your BigQuery Table ID:")

# PubMed Email and API key setup for Entrez
ENTREZ_EMAIL = st.sidebar.text_input("Enter your email for PubMed Entrez API:")
Entrez.email = ENTREZ_EMAIL  # Set email for NCBI Entrez

# Selectbox for data source selection
data_source = st.selectbox("Select Data Source", ["Google Patents", "Wikipedia", "PubMed", "All Combined"])

def search_pubmed(query, max_results=5):
    try:
        handle = Entrez.esearch(db="pubmed", term=query, retmax=max_results)
        record = Entrez.read(handle)
        handle.close()
        pubmed_ids = record["IdList"]

        if not pubmed_ids:
            st.write("No PubMed articles found for the query.")
            return []

        articles = []
        handle = Entrez.efetch(db="pubmed", id=pubmed_ids, rettype="abstract", retmode="text")
        abstracts = handle.read().split("\n\n")
        handle.close()

        for i, abstract in enumerate(abstracts):
            if i < len(pubmed_ids):
                articles.append({
                    "id": pubmed_ids[i],
                    "abstract": abstract
                })

        return articles

    except Exception as e:
        st.write(f"Error fetching PubMed data: {str(e)}")
        return []

def google_patent_search(query, num_results):
    service = build("customsearch", "v1", developerKey=GOOGLE_API_KEY)
    res = service.cse().list(q=query, cx=SEARCH_ENGINE_ID, num=num_results).execute()
    return res.get('items', [])

def store_in_bigquery(patent_data):
    if not project_id or not dataset_id or not table_id:
        st.write("Error: Please provide Project ID, Dataset ID, and Table ID in the sidebar.")
        return

    table_ref = bq_client.dataset(dataset_id).table(table_id)

    rows_to_insert = [{
        "paper_id": patent_data['paper_id'],
        "title": patent_data['title'],
        "link": patent_data['link'],
        "snippet": patent_data['snippet'],
        "html_content": patent_data['html_content'],
    }]

    job_config = bigquery.LoadJobConfig(
        schema=[
            bigquery.SchemaField("paper_id", "INTEGER"),
            bigquery.SchemaField("title", "STRING"),
            bigquery.SchemaField("link", "STRING"),
            bigquery.SchemaField("snippet", "STRING"),
            bigquery.SchemaField("html_content", "STRING"),
        ],
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON
    )

    try:
        load_job = bq_client.load_table_from_json(rows_to_insert, table_ref, job_config=job_config)
        load_job.result()
        st.write(f"Successfully inserted {patent_data['title']} into BigQuery")
    except Exception as e:
        st.write(f"Error occurred while inserting rows: {e}")

def scrape_html_content(url):
    try:
        loader = WebBaseLoader(url)
        documents = loader.load()
        html_content = "".join([doc.page_content for doc in documents])
        return html_content
    except Exception as e:
        st.write(f"Error scraping HTML content from {url}: {e}")
        return ""

def query_wikipedia(query):
    try:
        loader = WikipediaLoader(query=query)
        documents = loader.load()
        summaries = [doc.page_content for doc in documents]
        return summaries
    except Exception as e:
        st.write(f"Error querying Wikipedia: {e}")
        return []

def query_openai_llm(user_query, context):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": f"{user_query}\n\nContext: {context}"}],
            temperature=0.2
        )
        return response['choices'][0]['message']['content'] if response.get('choices') else "No response generated."
    except Exception as e:
        st.write(f"Error querying OpenAI: {str(e)}")
        return "An error occurred while generating the response."

st.title("Knowledge Generation System")

user_query = st.text_input("Ask OpenAI any question:")

query = st.text_input("Enter your search query:")

num_results = st.number_input("Enter the number of results to fetch:", min_value=1, max_value=10, value=5)

if query and num_results:
    if data_source in ["Google Patents", "All Combined"]:
        patent_results = google_patent_search(query, num_results)
        for idx, result in enumerate(patent_results):
            st.write(f"**{idx + 1}. {result['title']}**")
            patent_link = result.get('link', 'Link not available')
            st.write(f"Link: {patent_link}")
            html_content = scrape_html_content(patent_link)
            snippet = result.get('snippet', '').replace("...", "")
            st.write(f"Snippet: {snippet}")
            patent_data = {
                "paper_id": idx + 1,
                "title": result['title'],
                "link": patent_link,
                "snippet": snippet,
                "html_content": html_content
            }
            store_in_bigquery(patent_data)

    if data_source in ["Wikipedia", "All Combined"]:
        wikipedia_summaries = query_wikipedia(query)
        for summary in wikipedia_summaries:
            st.write(f"**Wikipedia Summary:** {summary}")

    if data_source in ["PubMed", "All Combined"]:
        pubmed_articles = search_pubmed(query)
        for article in pubmed_articles:
            st.write(f"**PubMed Article ID {article['id']}**: {article['abstract']}")

    if user_query:
        context_str = query
        if data_source == "All Combined":
            context_str += " (Combined from all sources)"
        response = query_openai_llm(user_query, context_str)
        st.write(f"**OpenAI Response:** {response}")