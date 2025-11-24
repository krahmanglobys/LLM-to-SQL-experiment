# DATA HIERARCHY CONTEXT

### CONTEXT: DATA HIERARCHY STRUCTURE
The system follows a strict top-down hierarchy. Use this tree to determine parent/child relationships:

1. **Client** (Root Level)
   └── **Products**
       ├── **Bundles** (Types: BA, UA)
       ├── **Groups** (Group1, Group2, etc.)
       └── **Organization**
           └── **Hierarchies**
               └── **Hierarchy Nodes**
                   ├── **Accounts**
                   │   ├── **Users** (Types: Type1, EndUser, CSR)
                   │   └── **Sub_Accounts** (Services)
                   │       └── **Data** (Usage Data / Reporting Data)
                   └── **Statement** (t_statement)

### CONTEXT: ID REFERENCE GUIDE & DEFINITIONS
When asked about specific IDs, refer to these definitions, scopes, and use cases:

**1. Client ID**
*   **Definition:** The absolute root level of the data structure.
*   **Scope:** Global umbrella; everything else resides inside this ID.
*   **Use Case:** Identifies the distinct business entity licensing the software.

**2. Product ID / Bundle ID**
*   **Definition:** Represents specific offerings (e.g., "BA" or "UA" bundles).
*   **Scope:** Defines the product layer.
*   **Use Case:** Determines feature availability, billing tiers, and what the client has purchased.

**3. Organization ID (Org ID)**
*   **Definition:** The container for operational structure within a Client/Product.
*   **Scope:** Holds Hierarchies, Accounts, and Statements.
*   **Use Case:** The primary "working level" ID used to locate specific hierarchies or groups of accounts.

**4. Account ID**
*   **Definition:** The main operational unit representing a customer or household.
*   **Relationships:** 
    *   Parent: Organization/Hierarchy.
    *   Child: Users and Sub_Accounts.
*   **Use Case:** The primary ID for linking specific customers to their users.

**5. User ID**
*   **Definition:** An individual login or profile attached to an Account.
*   **Types:** End User (Standard), CSR (Admin/Support).
*   **Use Case:** Authentication, permissions, and activity logging.

**6. Sub_Account ID**
*   **Definition:** Represents specific "Services" (e.g., Internet, Phone, TV).
*   **Relationships:** Child of Account ID.
*   **Scope:** Contains Usage Data and Reporting Data.
*   **Use Case:** Used to track data consumption (usage) for a specific service under a main Account.

**7. Statement ID**
*   **Definition:** A specific billing record (t_statement).
*   **Scope:** Generated at the Organization or Account level.
*   **Use Case:** Retrieving specific billing documents or report instances.

### INSTRUCTIONS
1. When explaining an ID, always mention its **Parent** (what it belongs to) and its **Children** (what it contains).
2. Clearly distinguish between **Account ID** (the customer entity) and **Sub_Account ID** (the specific service/usage data).
3. If asked about "Usage" or "Data," direct the user to the **Sub_Account ID**.
4. If asked about "Licensing" or "Business Entity," direct the user to the **Client ID**.