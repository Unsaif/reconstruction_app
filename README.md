# Metabolic Pathway Reconstruction App

This Streamlit application uses Google's Gemini Pro model to reconstruct metabolic pathways from scientific PDF documents. It extracts reactions, metabolites, enzymes, and regulation details, visualizing them as an interactive graph and a unified evidence viewer.

## Features

-   **PDF Analysis**: Upload multiple scientific papers (PDFs).
-   **AI Reconstruction**: Uses Gemini 1.5 Pro to extract structured metabolic data.
-   **Interactive Visualization**: Generates a bipartite graph (Substrate -> Reaction -> Product) of the pathway.
-   **Unified Viewer**: Split-screen view linking extracted data directly to evidence in the PDF.
-   **High-Quality Exports**: Download the pathway graph as High-Res PNG or SVG.

## Setup

### Prerequisites

-   Python 3.10+
-   A Google Cloud API Key with access to Gemini models.

### Local Installation

1.  **Clone the repository**:
    ```bash
    git clone <repository-url>
    cd reconstruction_app
    ```

2.  **Create a virtual environment**:
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set up Environment Variables**:
    Create a `.env` file in the root directory and add your Google API Key:
    ```
    GOOGLE_API_KEY=your_api_key_here
    ```

5.  **Run the App**:
    ```bash
    streamlit run app.py
    ```

## Docker

You can also run the application using Docker.

1.  **Build the image**:
    ```bash
    docker build -t reconstruction-app .
    ```

2.  **Run the container**:
    ```bash
    docker run -p 8502:8502 --env-file .env reconstruction-app
    ```
    *Note: Ensure your `.env` file exists and contains your API key.*

## License

[Your License Here]
