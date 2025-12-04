import streamlit as st
from google import genai
from google.genai import types
import os
from dotenv import load_dotenv
import json
import base64
import re
import fitz  # PyMuPDF
from rapidfuzz import fuzz
import streamlit.components.v1 as components
import graphviz

# Load API Key from .env file
load_dotenv()

# Initialize Gemini Client
try:
    api_key = os.environ.get("GOOGLE_API_KEY")
    # Docker might pass quotes literally from .env, so we strip them
    if api_key:
        api_key = api_key.strip().strip("'").strip('"')
    client = genai.Client(api_key=api_key)
except Exception as e:
    st.error(f"Error initializing Gemini Client: {e}. Make sure GOOGLE_API_KEY is in your .env file.")
    st.stop()

st.set_page_config(page_title="Metabolic Pathway Reconstruction", layout="wide")

st.title("Metabolic Pathway Reconstruction")
st.markdown("""
Upload a PDF of a scientific paper to extract and reconstruct a metabolic pathway.
This tool uses Google's Gemini 2.5 Flash model to generate a structured JSON model and a plain-language explanation.
""")

def smart_clean_name(name):
    """Cleans up chemical names by removing common prefixes/suffixes."""
    name = re.sub(r'^\d+[\.,]\d+-', '', name)
    name = re.sub(r'\(.*?synthetic.*?\)', '', name, flags=re.IGNORECASE)
    return name.strip()

def find_text_fuzzy(pdf_bytes, text_quotes, threshold=85):
    """
    Finds text in PDF using fuzzy matching and returns annotations.
    """
    annotations = []
    # Normalize queries to list of dicts
    normalized_queries = []
    for q in text_quotes:
        if isinstance(q, str):
            normalized_queries.append({'text': q, 'color': "rgba(255, 255, 0, 0.4)"})
        elif isinstance(q, dict):
            normalized_queries.append(q)

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page_num, page in enumerate(doc):
            words = page.get_text("words") # list of (x0, y0, x1, y1, "word", block_no, line_no, word_no)
            
            for query_item in normalized_queries:
                quote = query_item['text']
                color = query_item.get('color', "rgba(255, 255, 0, 0.4)")
                
                # Clean quote
                quote_clean = re.sub(r'\s+', ' ', quote).strip()
                if len(quote_clean) < 5: continue # Skip very short quotes
                
                # Reconstruct full text from words to run fuzzy match
                full_text = " ".join([w[4] for w in words])
                
                # Use rapidfuzz to find the best partial match
                # partial_ratio is good for finding a substring
                score = fuzz.partial_ratio(quote_clean.lower(), full_text.lower())
                
                if score >= threshold:
                    # Now we need to find *where* in the words list this match occurred.
                    # This is tricky with simple string matching. 
                    # A robust way is to slide a window of words and check similarity.
                    
                    quote_word_count = len(quote_clean.split())
                    # We'll check windows of varying sizes around the expected length
                    
                    best_window_score = 0
                    best_window_indices = None
                    
                    # Optimization: Only check windows if the page score is high enough
                    for i in range(len(words)):
                        # Check windows of varying sizes around the expected length
                        for window_size in range(max(1, quote_word_count - 2), quote_word_count + 5):
                            if i + window_size > len(words):
                                break
                                
                            window_text = " ".join([w[4] for w in words[i:i+window_size]])
                            window_score = fuzz.ratio(quote_clean.lower(), window_text.lower())
                            
                            if window_score > best_window_score:
                                best_window_score = window_score
                                best_window_indices = (i, i + window_size)
                    
                    if best_window_score >= threshold:
                        start_idx, end_idx = best_window_indices
                        matched_words = words[start_idx:end_idx]
                        
                        # Create a bounding box for the whole match (or per line)
                        # For simplicity, let's create boxes for each word to ensure wrapping works
                        for w in matched_words:
                            annotations.append({
                                "page": page_num + 1,
                                "x": w[0],
                                "y": w[1],
                                "width": w[2] - w[0],
                                "height": w[3] - w[1],
                                "color": color, 
                                "quote": quote # Store quote for reference
                            })
                            
    except Exception as e:
        st.warning(f"Error in fuzzy search: {e}")
        
    return annotations

def pathway_viewer_component(pdf_bytes, reactions, annotations, height=900):
    """
    Custom Streamlit component to render a split view: Reactions Table + PDF Viewer.
    """
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    annotations_json = json.dumps(annotations)
    reactions_json = json.dumps(reactions)
    
    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
        <style>
            body {{ margin: 0; padding: 0; background-color: #f8f9fa; font-family: 'Inter', sans-serif; }}
            .container {{ display: flex; height: {height}px; }}
            
            /* Left Panel: Reactions Table */
            .table-panel {{ 
                flex: 1; 
                overflow-y: auto; 
                padding: 20px; 
                border-right: 1px solid #ddd; 
                background: white;
            }}
            
            .reaction-card {{
                background: white;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                padding: 16px;
                margin-bottom: 16px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                transition: transform 0.2s;
            }}
            .reaction-card:hover {{ transform: translateY(-2px); box-shadow: 0 4px 8px rgba(0,0,0,0.1); }}
            
            .rxn-header {{ font-weight: 600; color: #1a73e8; margin-bottom: 8px; display: flex; justify-content: space-between; }}
            .rxn-eq {{ font-family: monospace; background: #f1f3f4; padding: 8px; border-radius: 4px; margin-bottom: 12px; font-size: 0.9em; }}
            
            .rxn-details {{ display: flex; gap: 20px; font-size: 0.85em; color: #5f6368; margin-bottom: 12px; }}
            .detail-col {{ flex: 1; }}
            
            .evidence-btn {{
                background: #e8f0fe;
                color: #1a73e8;
                border: none;
                padding: 4px 12px;
                border-radius: 16px;
                cursor: pointer;
                font-size: 0.8em;
                margin-right: 8px;
                margin-bottom: 4px;
                transition: background 0.2s;
            }}
            .evidence-btn:hover {{ background: #d2e3fc; }}
            
            /* Right Panel: PDF Viewer */
            #viewerContainer {{ 
                flex: 1; 
                overflow-y: auto; 
                background-color: #525659;
                display: flex;
                flex-direction: column;
                align-items: center;
                padding: 20px;
                gap: 20px;
            }}
            
            .pageContainer {{ position: relative; background-color: white; box-shadow: 0 0 10px rgba(0,0,0,0.3); }}
            .highlight {{ position: absolute; pointer-events: none; z-index: 1; mix-blend-mode: multiply; }}
            .highlight.active {{ background-color: rgba(255, 200, 0, 0.6); z-index: 2; box-shadow: 0 0 4px rgba(0,0,0,0.2); }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="table-panel" id="reactionList">
                <!-- Reactions will be populated here -->
            </div>
            <div id="viewerContainer">
                <!-- PDF pages will be populated here -->
            </div>
        </div>

        <script>
            pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
            const pdfData = atob("{base64_pdf}");
            const annotations = {annotations_json};
            const reactions = {reactions_json};
            
            // 1. Render Reactions Table
            const reactionList = document.getElementById('reactionList');
            
            reactions.forEach((rxn, index) => {{
                const card = document.createElement('div');
                card.className = 'reaction-card';
                
                // Prepare data
                const enzyme = Array.isArray(rxn.enzyme) ? rxn.enzyme.join(", ") : (rxn.enzyme || "Unknown");
                const subs = rxn.substrates ? rxn.substrates.join(" + ") : "";
                const prods = rxn.products ? rxn.products.join(" + ") : "";
                
                // New fields
                const organ = rxn.organ || "Unknown Organ";
                const organism = rxn.organism || "Unknown Organism";
                const type = rxn.type || "Metabolic";
                const certainty = rxn.certainty || "Confirmed";
                const primarySource = rxn.primary_source ? `Ref: ${{rxn.primary_source}}` : "";
                
                // Certainty badge color
                let certaintyColor = "#e8f0fe"; // Default Blue
                let certaintyTextColor = "#1967d2";
                if (certainty.toLowerCase() === "hypothetical") {{
                    certaintyColor = "#fef7e0"; // Light Orange/Yellow
                    certaintyTextColor = "#b06000"; // Dark Orange
                }} else {{
                    certaintyColor = "#e6f4ea"; // Greenish for confirmed
                    certaintyTextColor = "#137333";
                }}
                
                // Regulation string
                let regStr = "None";
                if (rxn.regulation) {{
                    if (typeof rxn.regulation === 'string') regStr = rxn.regulation;
                    else if (typeof rxn.regulation === 'object') {{
                        const parts = [];
                        if (rxn.regulation.inhibitors && rxn.regulation.inhibitors.length) parts.push(`Inhibitors: ${{rxn.regulation.inhibitors.length}}`);
                        if (rxn.regulation.activators && rxn.regulation.activators.length) parts.push(`Activators: ${{rxn.regulation.activators.length}}`);
                        if (parts.length) regStr = parts.join(", ");
                    }}
                }}

                // Evidence Buttons
                let evidenceHtml = '';
                if (rxn.evidence && rxn.evidence.length) {{
                    rxn.evidence.forEach((quote, qIdx) => {{
                        // Escape quote for title attribute (HTML context)
                        const safeQuote = quote.replace(/"/g, '&quot;');
                        // Pass indices to function instead of string to avoid escaping hell
                        evidenceHtml += `<button class="evidence-btn" onclick="scrollToQuote(${{index}}, ${{qIdx}})" title="${{safeQuote}}">📄 Cite ${{qIdx + 1}}</button>`;
                    }});
                }} else {{
                    evidenceHtml = '<span style="color: #999; font-size: 0.8em;">No specific citation</span>';
                }}
                
                // Primary Source HTML
                let sourceHtml = '';
                if (primarySource) {{
                    sourceHtml = `<div style="font-size: 0.8em; color: #5f6368; margin-top: 4px; font-style: italic;">${{primarySource}}</div>`;
                }}

                card.innerHTML = `
                    <div class="rxn-header">
                        <span>${{rxn.id || 'R'+(index+1)}}</span>
                        <span style="font-weight: 400; font-size: 0.9em;">${{enzyme}}</span>
                    </div>
                    
                    <div style="display: flex; gap: 8px; margin-bottom: 8px; flex-wrap: wrap;">
                        <span style="background: #f1f3f4; color: #3c4043; padding: 2px 8px; border-radius: 12px; font-size: 0.75em; font-weight: 600;">${{type}}</span>
                        <span style="background: ${{certaintyColor}}; color: ${{certaintyTextColor}}; padding: 2px 8px; border-radius: 12px; font-size: 0.75em; font-weight: 600;">${{certainty}}</span>
                        <span style="background: #fce8e6; color: #c5221f; padding: 2px 8px; border-radius: 12px; font-size: 0.75em; font-weight: 600;">${{organ}}</span>
                        <span style="background: #e8f0fe; color: #1967d2; padding: 2px 8px; border-radius: 12px; font-size: 0.75em; font-weight: 600;">${{organism}}</span>
                    </div>

                    <div class="rxn-eq">${{subs}} ➝ ${{prods}}</div>
                    <div class="rxn-details">
                        <div class="detail-col"><strong>Regulation:</strong><br>${{regStr}}</div>
                    </div>
                    ${{sourceHtml}}
                    <div style="margin-top: 8px;">
                        ${{evidenceHtml}}
                    </div>
                `;
                reactionList.appendChild(card);
            }});

            // 2. Render PDF
            async function renderPdf() {{
                const loadingTask = pdfjsLib.getDocument({{data: pdfData}});
                const pdf = await loadingTask.promise;
                const container = document.getElementById('viewerContainer');
                
                for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {{
                    const page = await pdf.getPage(pageNum);
                    const scale = 1.2; // Slightly smaller for split view
                    const viewport = page.getViewport({{scale: scale}});
                    
                    const pageDiv = document.createElement('div');
                    pageDiv.className = 'pageContainer';
                    pageDiv.style.width = viewport.width + 'px';
                    pageDiv.style.height = viewport.height + 'px';
                    pageDiv.id = 'page-' + pageNum;
                    
                    const canvas = document.createElement('canvas');
                    const context = canvas.getContext('2d');
                    canvas.height = viewport.height;
                    canvas.width = viewport.width;
                    
                    pageDiv.appendChild(canvas);
                    container.appendChild(pageDiv);
                    
                    await page.render({{canvasContext: context, viewport: viewport}}).promise;
                    
                    // Add highlights
                    const pageAnnotations = annotations.filter(a => a.page === pageNum);
                    pageAnnotations.forEach(ann => {{
                        const div = document.createElement('div');
                        div.className = 'highlight';
                        div.dataset.quote = ann.quote; // Store quote for lookup
                        div.style.left = (ann.x * scale) + 'px';
                        div.style.top = (ann.y * scale) + 'px';
                        div.style.width = (ann.width * scale) + 'px';
                        div.style.height = (ann.height * scale) + 'px';
                        div.style.backgroundColor = ann.color;
                        pageDiv.appendChild(div);
                    }});
                }}
            }}
            renderPdf();

            // 3. Scroll Function
            window.scrollToQuote = function(rIdx, eIdx) {{
                // Retrieve quote from reactions object using indices
                if (!reactions[rIdx] || !reactions[rIdx].evidence[eIdx]) {{
                    console.error("Quote not found for indices:", rIdx, eIdx);
                    return;
                }}
                const quote = reactions[rIdx].evidence[eIdx];
                
                // Find annotations matching this quote
                // We match loosely on the quote text stored in dataset
                const highlights = document.querySelectorAll('.highlight');
                let target = null;
                
                for (let h of highlights) {{
                    if (h.dataset.quote === quote) {{
                        target = h;
                        break;
                    }}
                }}
                
                if (target) {{
                    // Scroll container to this element
                    target.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                    
                    // Add active class for visual feedback
                    document.querySelectorAll('.highlight.active').forEach(el => el.classList.remove('active'));
                    // Highlight all words for this quote
                    for (let h of highlights) {{
                        if (h.dataset.quote === quote) {{
                            h.classList.add('active');
                        }}
                    }}
                }} else {{
                    console.log("Quote highlight not found in PDF:", quote);
                }}
            }};
        </script>
    </body>
    </html>
    """
    components.html(html_code, height=height, scrolling=False) # Scrolling handled inside component

def generate_graphviz_dot(json_data):
    try:
        data = json_data if isinstance(json_data, dict) else json.loads(json_data)
        
        # Graph settings for better layout
        dot = ['digraph MetabolicPathway {']
        dot.append('  rankdir=LR;') # Left-to-Right flow
        dot.append('  nodesep=0.6;')
        dot.append('  ranksep=0.8;')
        dot.append('  splines=ortho;') # Orthogonal lines for cleaner look
        dot.append('  overlap=false;')
        
        # Styles
        dot.append('  node [fontname="Helvetica", fontsize=10];')
        dot.append('  edge [fontname="Helvetica", fontsize=9];')
        
        # Common cofactors to exclude from visualization to prevent "hairballs"
        exclude_metabolites = {
            'h2o', 'water', 'h+', 'proton', 'o2', 'oxygen', 'co2', 
            'atp', 'adp', 'amp', 'nad+', 'nadh', 'nadp+', 'nadph', 
            'pi', 'phosphate', 'ppi', 'coa', 'coenzyme a'
        }

        if 'reactions' in data:
            for i, rxn in enumerate(data['reactions']):
                # Handle cases where substrates/products might be empty or missing
                substrates = rxn.get('substrates', [])
                products = rxn.get('products', [])
                enzyme = rxn.get('enzyme', 'unknown')
                
                if not substrates or not products:
                    continue

                # Handle enzyme (can be list or string)
                if isinstance(enzyme, list):
                    enzyme = ", ".join(enzyme)
                enzyme_clean = str(enzyme).replace(" activity", "")
                
                # Create a unique node for the reaction itself (Bipartite graph)
                rxn_id = f"rxn_{i}"
                rxn_label = enzyme_clean
                # Reaction node style (small ellipse or diamond)
                dot.append(f'  {rxn_id} [shape=ellipse, style=filled, fillcolor="#fff9c4", label="{rxn_label}", fontsize=8];')

                # Edges: Substrate -> Reaction Node
                for s_full in substrates:
                    s_clean = smart_clean_name(s_full)
                    if s_clean.lower() in exclude_metabolites:
                        continue
                        
                    s_id = "met_" + str(abs(hash(s_clean)))
                    # Metabolite node style (box)
                    dot.append(f'  {s_id} [shape=box, style=filled, fillcolor="#e1f5fe", label="{s_clean}"];')
                    dot.append(f'  {s_id} -> {rxn_id};')

                # Edges: Reaction Node -> Product
                for p_full in products:
                    p_clean = smart_clean_name(p_full)
                    if p_clean.lower() in exclude_metabolites:
                        continue
                        
                    p_id = "met_" + str(abs(hash(p_clean)))
                    # Metabolite node style (box)
                    dot.append(f'  {p_id} [shape=box, style=filled, fillcolor="#e1f5fe", label="{p_clean}"];')
                    dot.append(f'  {rxn_id} -> {p_id};')

        dot.append('}')
        return "\n".join(dot)
    except Exception as e:
        st.error(f"Error generating Graphviz diagram: {e}")
        return None

uploaded_files = st.file_uploader("Choose PDF file(s)", type="pdf", accept_multiple_files=True)

if uploaded_files:
    # Initialize session state for analysis results if not present
    if "analysis_result" not in st.session_state:
        st.session_state.analysis_result = None
    if "full_text" not in st.session_state:
        st.session_state.full_text = None
    if "all_pdf_bytes" not in st.session_state:
        st.session_state.all_pdf_bytes = []
    
    # Check if we need to run analysis (button click)
    if st.button("Generate Reconstruction"):
        with st.spinner("Analyzing PDF(s) and reconstructing pathway..."):
            try:
                contents = []
                all_pdf_bytes = []
                for uploaded_file in uploaded_files:
                    pdf_bytes = uploaded_file.getvalue()
                    all_pdf_bytes.append(pdf_bytes)
                    contents.append(types.Part.from_bytes(
                        data=pdf_bytes,
                        mime_type='application/pdf',
                    ))
                
                # Store PDF bytes in session state
                st.session_state.all_pdf_bytes = all_pdf_bytes

                prompt = """## Metabolic Pathway Reconstruction Prompt

**Task**  
You are an expert in systems biology and bioinformatics.  
Your job is to extract and reconstruct a metabolic pathway ONLY from the contents of the uploaded PDF(s).  
Synthesize information from ALL provided documents to build a comprehensive model.
Do not use outside knowledge — if the documents lack information, say so explicitly.

**Goal**  
Output a structured pathway model that captures:
- metabolites
- enzymes
- reaction directionality
- cofactors
- regulators (feedback, inhibition, activation)
- compartments (if stated)
- **organ/tissue context**
- **organism/model context**
- **reaction type (metabolic vs transport)**
- **certainty status (confirmed vs hypothetical)**
- **primary source (if evidence is secondary)**

---

### Extraction Procedure

**Step 1 — Identify biochemical entities**  
Extract all relevant biological elements mentioned in the documents:
- metabolites / intermediates
- enzymes
- transporters
- coenzymes
- reaction intermediates

Keep all names exactly as written in the documents.  
If multiple names or synonyms are listed, include them.

---

**Step 2 — List metabolic reactions**  
For each reaction mentioned, identify:

- Substrate(s)
- Product(s)
- Enzyme(s)
- Required cofactors (e.g., ATP, NADH, FAD, etc.)
- Directionality (“reversible” or “irreversible”)
- Any pathway branching
- **Organ/Tissue**: Where does this reaction occur? (e.g., Liver, Gut, Kidney). If unknown, use "Unknown".
- **Organism**: In what organism or model was this found? (e.g., Human, Mouse, Rat, Microbial).
- **Type**: Is this a "Metabolic" reaction or a "Transport" reaction?
- **Certainty**: Is this reaction "Confirmed" (stated as fact) or "Hypothetical" (suggested, proposed, hypothesized)?
- **Primary Source**: If the text cites another paper for this reaction (e.g., "as shown by Smith et al."), extract that citation here. If it appears to be a primary finding of this text or no citation is given, leave null.

**CRITICAL: Ordering**
Organize the reactions in a logical, physiological order, starting from **Ingestion/Uptake** $\to$ **Metabolism** $\to$ **Excretion/Secretion**.

Represent each reaction as a structured object.

---

**Step 3 — Extract regulatory information**  
If present in the text, identify:
- inhibitors
- activators
- transcriptional/gene-level regulators
- allosteric feedback mechanisms

If regulation is not described, leave these fields empty.

---

**Step 4 — Build the JSON Pathway Model**

Output a structured JSON representation like this:

```json
{
  "metabolites": [],
  "enzymes": [],
        "reactions": [
          {
            "id": "",
            "type": "Metabolic", // or "Transport"
            "certainty": "Confirmed", // or "Hypothetical"
            "organ": "Liver",
            "organism": "Human",
            "primary_source": "Smith et al. 2020", // or null
            "substrates": [],
            "products": [],
            "enzyme": "",
            "cofactors": [],
            "reversible": null,
            "regulation": {
              "inhibitors": [],
              "activators": []
            },
            "compartment": "",
            "evidence": ["exact quote 1", "exact quote 2"]
          }
        ]
      }
      ```
      
      ### Rules for JSON
      
      - Use exact names from the documents  
      - If something is unknown, write `"unknown"` or `null`  
      - If multiple interpretations exist, list them all  
      - Do **not** insert external biological knowledge or inferred steps  
      - **"evidence"**: This field is MANDATORY for each reaction. You MUST extract at least 1-2 EXACT string quotes from the text that support this specific reaction. **CRITICAL**: The quotes must be EXACT substrings found in the documents.

---

### Step 5 — Evidence Citations

For each reaction, quote or summarize the specific line(s) or section(s) from the documents that justify its inclusion.  
If no clear citation exists, state that explicitly.

---

### Final Deliverables

1. **JSON metabolic pathway model**
2. **Plain-language explanation** (short summary) that describes:
   - pathway purpose  
   - the sequence and logic of reactions  
   - key regulatory bottlenecks and control points  
   - any ambiguous or incomplete sections  

---

### Output Rules

- Base all information ONLY on content found in the documents  
- If information is incomplete or missing, describe what data would be needed to complete the reconstruction  
- If the pathway includes alternatives, branching, or cycles, represent them clearly in structure and text  
- Use clear, unambiguous terminology everywhere  

---

### Additional Notes

- Do not invent metabolites or reactions that are not explicitly in the documents  
- Keep reporting precise and limited to what’s visible  
- If diagrams appear without labels, describe what can be interpreted and what cannot"""
                
                contents.append(prompt)
# gemini-3-pro-preview gemini-2.5-flash
                response = client.models.generate_content(
                    model="gemini-3-pro-preview",
                    contents=contents
                )
                
                full_text = response.text
                st.session_state.full_text = full_text
                
                # Extract JSON block
                # Try to find JSON between triple backticks
                json_match = re.search(r'```(?:json)?\s*(.*?)```', full_text, re.DOTALL)
                
                json_str = ""
                if json_match:
                    json_str = json_match.group(1)
                else:
                    # Fallback: Try to find the first { and last }
                    start_idx = full_text.find('{')
                    end_idx = full_text.rfind('}')
                    if start_idx != -1 and end_idx != -1:
                        json_str = full_text[start_idx:end_idx+1]
                
                json_data = None
                if json_str:
                    try:
                        json_data = json.loads(json_str)
                        st.session_state.analysis_result = json_data
                    except json.JSONDecodeError as e:
                        st.error(f"JSON Parsing Error: {e}")
                        with st.expander("View Raw Output (Debug)"):
                            st.code(full_text)
                else:
                    st.warning("No JSON block found in response.")
                    with st.expander("View Raw Output (Debug)"):
                        st.code(full_text)
                
                st.success("Analysis Complete!")
                
            except Exception as e:
                st.error(f"An error occurred: {e}")

    # Display Results if available in session state
    if st.session_state.analysis_result:
        json_data = st.session_state.analysis_result
        full_text = st.session_state.full_text
        
        # 1. Visualization (Graphviz)
        if json_data:
            st.subheader("Pathway Visualization")
            dot_code = generate_graphviz_dot(json_data)
            if dot_code:
                st.graphviz_chart(dot_code)
                
                # Download buttons
                col1, col2, col3 = st.columns(3)
                with col1:
                    try:
                        # Render High-Res PNG (300 DPI)
                        # Inject DPI attribute into the DOT code
                        dot_code_high_res = dot_code.replace('{', '{\n  dpi=300;', 1)
                        graph = graphviz.Source(dot_code_high_res)
                        png_bytes = graph.pipe(format='png')
                        st.download_button(
                            label="Download Graph (High-Res PNG)",
                            data=png_bytes,
                            file_name="pathway_graph_highres.png",
                            mime="image/png"
                        )
                    except Exception as e:
                        st.warning(f"Could not generate PNG download: {e}")
                
                with col2:
                    try:
                        # Render SVG
                        graph = graphviz.Source(dot_code)
                        svg_bytes = graph.pipe(format='svg')
                        st.download_button(
                            label="Download Graph (SVG)",
                            data=svg_bytes,
                            file_name="pathway_graph.svg",
                            mime="image/svg+xml"
                        )
                    except Exception as e:
                        st.warning(f"Could not generate SVG download: {e}")

                with col3:
                    st.download_button(
                        label="Download Graph Source (DOT)",
                        data=dot_code,
                        file_name="pathway_graph.dot",
                        mime="text/vnd.graphviz"
                    )
        
        # 2. Unified Pathway Viewer (Table + PDF)
        if json_data and 'reactions' in json_data:
            st.subheader("Pathway Details & Evidence")
            
            # Collect all evidence quotes with their certainty for annotation search
            evidence_items = []
            for rxn in json_data['reactions']:
                if 'evidence' in rxn:
                    certainty = rxn.get('certainty', 'Confirmed')
                    # Determine color based on certainty
                    # Confirmed = Yellow (rgba(255, 255, 0, 0.4))
                    # Hypothetical = Orange (rgba(255, 165, 0, 0.5))
                    color = "rgba(255, 255, 0, 0.4)"
                    if certainty and certainty.lower() == "hypothetical":
                        color = "rgba(255, 165, 0, 0.5)"
                        
                    if rxn['evidence'] and isinstance(rxn['evidence'], list):
                        for quote in rxn['evidence']:
                            evidence_items.append({
                                'text': quote,
                                'color': color
                            })
            
            # Create tabs for each uploaded file
            # Use session state bytes if available, otherwise try to use uploaded_files (but bytes are safer)
            if st.session_state.all_pdf_bytes and uploaded_files:
                # Ensure we have matching lengths, otherwise fallback or warn
                # Since uploaded_files persists, we can match by index
                tabs = st.tabs([f.name for f in uploaded_files])
                
                for i, tab in enumerate(tabs):
                    if i < len(st.session_state.all_pdf_bytes):
                        with tab:
                            pdf_bytes = st.session_state.all_pdf_bytes[i]
                            
                            # Find annotations using fuzzy search
                            # Pass the list of dicts directly
                            annotations = find_text_fuzzy(pdf_bytes, evidence_items)
                            
                            st.caption(f"Found {len(annotations)} highlights.")
                            
                            # Render unified viewer
                            pathway_viewer_component(
                                pdf_bytes, 
                                json_data['reactions'],
                                annotations, 
                                height=800
                            )
                
                # 3. Metabolites & Enzymes (Supplementary)
                # 3. Metabolites & Enzymes (Supplementary)
                with st.expander("Supplementary Data: Reactions, Metabolites & Enzymes"):
                    tab_rxn, tab_met, tab_enz = st.tabs(["Reactions", "Metabolites", "Enzymes"])
                    
                    with tab_rxn:
                        if 'reactions' in json_data:
                            # Format reactions for display
                            formatted_reactions = []
                            for rxn in json_data['reactions']:
                                formatted_rxn = rxn.copy()
                                
                                # Join lists into strings
                                for key in ['substrates', 'products', 'cofactors']:
                                    if key in formatted_rxn and isinstance(formatted_rxn[key], list):
                                        formatted_rxn[key] = ", ".join(formatted_rxn[key])
                                
                                # Handle enzyme (can be list or string)
                                if 'enzyme' in formatted_rxn and isinstance(formatted_rxn['enzyme'], list):
                                    formatted_rxn['enzyme'] = ", ".join(formatted_rxn['enzyme'])

                                # Format regulation
                                if 'regulation' in formatted_rxn:
                                    reg = formatted_rxn['regulation']
                                    reg_str = ""
                                    if isinstance(reg, dict):
                                        inhibitors = reg.get('inhibitors', [])
                                        activators = reg.get('activators', [])
                                        
                                        if inhibitors:
                                            # Check if inhibitors is a list of strings or objects
                                            if inhibitors and isinstance(inhibitors[0], dict):
                                                inh_list = [f"{i.get('regulator', 'Unknown')} ({i.get('effect', '')})" for i in inhibitors]
                                                reg_str += f"Inhibitors: {', '.join(inh_list)}; "
                                            else:
                                                reg_str += f"Inhibitors: {', '.join(inhibitors)}; "
                                        
                                        if activators:
                                            # Check if activators is a list of strings or objects
                                            if activators and isinstance(activators[0], dict):
                                                act_list = [f"{a.get('regulator', 'Unknown')} ({a.get('effect', '')})" for a in activators]
                                                reg_str += f"Activators: {', '.join(act_list)}"
                                            else:
                                                reg_str += f"Activators: {', '.join(activators)}"
                                    
                                    formatted_rxn['regulation'] = reg_str.strip('; ')
                                
                                # Format evidence
                                if 'evidence' in formatted_rxn and isinstance(formatted_rxn['evidence'], list):
                                     formatted_rxn['evidence'] = " | ".join(formatted_rxn['evidence'])
                                
                                # Ensure new fields are present for dataframe consistency
                                for key in ['type', 'organ', 'organism', 'certainty', 'primary_source']:
                                    if key not in formatted_rxn:
                                        formatted_rxn[key] = "Unknown" if key != 'primary_source' else None

                                formatted_reactions.append(formatted_rxn)
                            
                            st.dataframe(formatted_reactions, use_container_width=True)
                        else:
                            st.info("No reactions found.")

                    with tab_met:
                        if 'metabolites' in json_data:
                            st.dataframe(json_data['metabolites'], use_container_width=True)
                        else:
                            st.info("No metabolites found.")
                    with tab_enz:
                        if 'enzymes' in json_data:
                            st.dataframe(json_data['enzymes'], use_container_width=True)
                        else:
                            st.info("No enzymes found.")

        # 4. Plain Language Explanation
        st.subheader("Explanation")
        # Remove the JSON block from the text
        explanation_text = re.sub(r'```json\n.*?\n```', '', full_text, flags=re.DOTALL).strip()
        
        # Clean up specific headers
        # Remove "1. JSON metabolic pathway model" and "2. Plain-language explanation..."
        # Also remove "### Final Deliverables" if present
        explanation_text = re.sub(r'### Final Deliverables\s*', '', explanation_text, flags=re.IGNORECASE)
        explanation_text = re.sub(r'\d+\.\s*\*\*JSON metabolic pathway model\*\*\s*', '', explanation_text, flags=re.IGNORECASE)
        explanation_text = re.sub(r'\d+\.\s*\*\*Plain-language explanation\*\*.*?\n', '', explanation_text, flags=re.IGNORECASE)
        # Remove just the header "Plain-language explanation" if it appears as a header
        explanation_text = re.sub(r'### Plain-Language Explanation.*?\n', '', explanation_text, flags=re.IGNORECASE)
        
        st.markdown(explanation_text)

        # 5. Raw JSON - Moved to very bottom
        # 5. Raw Data & Debugging
        st.divider()
        st.subheader("Raw Data & Debugging")
        
        with st.expander("View Raw JSON Model"):
            st.json(json_data)
            
        with st.expander("View Full LLM Response (Debug)"):
            st.text(full_text)

