# LLM-to-SQL Query Generator

A powerful tool that converts natural language questions into SQL queries using Large Language Models and intelligent schema matching.

## 🌟 Features

- **Natural Language to SQL**: Convert plain English questions into precise SQL queries
- **Intelligent Schema Matching**: Uses FAISS vector similarity search to find relevant database tables
- **Multi-attempt Validation**: Automatically retries and refines queries for accuracy
- **Interactive CLI**: User-friendly command-line interface
- **Azure OpenAI Integration**: Leverages advanced language models for query generation
- **Schema-aware**: Validates queries against actual database schema

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- Azure OpenAI API access
- Matcha API access (or your database API)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/krahmanglobys/LLM-to-SQL-experiment.git
   cd LLM-to-SQL-experiment
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables:**
   
   Create a `.env` file in the project root with the following variables:
   ```env
   # Azure OpenAI Configuration
   AZURE_OPENAI_ENDPOINT=your_azure_openai_endpoint
   AZURE_OPENAI_API_KEY=your_azure_openai_key
   AZURE_OPENAI_DEPLOYMENT_NAME=your_deployment_name
   AZURE_OPENAI_API_VERSION=2024-05-01-preview
   
   # Matcha API Configuration
   MATCHA_BASE_URL=https://matcha.harriscomputer.com/rest/api/v1
   MATCHA_API_KEY=your_matcha_api_key
   MATCHA_MISSION_ID=your_mission_id
   
   # Schema Configuration
   SCHEMA_CSV_PATH=attwln_dbo_schem.txt
   FAISS_INDEX_PATH=schema_tables.faiss
   METADATA_PATH=schema_tables_metadata.json
   ```

4. **Initialize the schema index (first time only):**
   ```bash
   python3 preprocess.py
   ```

### Usage

#### Interactive Mode (Recommended)

Run the script and follow the prompts:

```bash
python3 llm_to_query.py
```

You'll see:
```
🔍 LLM-to-SQL Query Generator
==================================================
Enter your natural language question to convert to SQL:
(Press Enter twice when finished, or Ctrl+C to exit)

```

#### Example Usage

**Input:**
```
Show me all customers who made orders in the last 30 days
with their total order value
```

**Output:**
```sql
SELECT 
    c.CustomerID,
    c.CustomerName,
    c.Email,
    SUM(od.Quantity * od.UnitPrice) as TotalOrderValue,
    COUNT(DISTINCT o.OrderID) as NumberOfOrders
FROM dbo.Customers c
INNER JOIN dbo.Orders o ON c.CustomerID = o.CustomerID
INNER JOIN dbo.OrderDetails od ON o.OrderID = od.OrderID
WHERE o.OrderDate >= DATEADD(day, -30, GETDATE())
GROUP BY c.CustomerID, c.CustomerName, c.Email
ORDER BY TotalOrderValue DESC
```

## 📁 Project Structure

```
LLM-to-SQL-experiment/
├── llm_to_query.py          # Main interactive script
├── preprocess.py            # Schema preprocessing and FAISS index creation
├── requirements.txt         # Python dependencies
├── .env                     # Environment variables (create this)
├── .env.example            # Example environment file
├── attwln_dbo_schem.txt    # Database schema file
├── schema_tables.faiss     # FAISS index (generated)
├── schema_tables_metadata.json # Schema metadata (generated)
├── data.ipynb              # Jupyter notebook for exploration
└── README.md               # This file
```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `AZURE_OPENAI_ENDPOINT` | Your Azure OpenAI service endpoint | ✅ |
| `AZURE_OPENAI_API_KEY` | Your Azure OpenAI API key | ✅ |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | Your GPT deployment name | ✅ |
| `MATCHA_BASE_URL` | Matcha API base URL | ✅ |
| `MATCHA_API_KEY` | Matcha API authentication key | ✅ |
| `MATCHA_MISSION_ID` | Your Matcha mission ID | ✅ |
| `SCHEMA_CSV_PATH` | Path to schema file | ❌ (default: attwln_dbo_schem.txt) |
| `FAISS_INDEX_PATH` | FAISS index file path | ❌ (default: schema_tables.faiss) |
| `METADATA_PATH` | Metadata file path | ❌ (default: schema_tables_metadata.json) |

### Schema Format

The schema file should contain table and column information in a format that can be processed by the preprocessing script. See `attwln_dbo_schem.txt` for an example.

## 🎯 How It Works

1. **Schema Indexing**: The system creates a FAISS vector index of your database schema
2. **Question Processing**: Your natural language question is analyzed and converted to embeddings
3. **Schema Matching**: Relevant tables and columns are found using similarity search
4. **SQL Generation**: GPT generates SQL queries using the matched schema context
5. **Validation**: The system validates and refines the query through multiple attempts

## 🛠 Advanced Usage

### Customizing Max Attempts

The system tries up to 3 times by default to generate a valid query. This is configured in the code but can be modified as needed.

### Adding Custom Schema

1. Update your schema file (`attwln_dbo_schem.txt`)
2. Re-run the preprocessing script:
   ```bash
   python3 preprocess.py
   ```

### Debugging

For detailed output and debugging information, check the console output which includes:
- Schema matching results
- Generated prompts
- Full LLM responses
- Extracted SQL queries

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🐛 Troubleshooting

### Common Issues

1. **FAISS Index Error**: If you see "could not open schema_tables.faiss for reading":
   ```bash
   python3 preprocess.py
   ```

2. **Environment Variables**: Ensure all required environment variables are set in your `.env` file

3. **API Errors**: Check your Azure OpenAI and Matcha API credentials and endpoints

4. **Schema Issues**: Ensure your schema file is properly formatted and accessible

### Getting Help

- Check the console output for detailed error messages
- Ensure all dependencies are installed correctly
- Verify your environment variables are set properly
- Test your API connections independently

## 📧 Support

For questions, issues, or contributions, please open an issue in the GitHub repository.

---

**Made with ❤️ by the LLM-to-SQL team**