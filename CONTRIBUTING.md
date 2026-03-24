# Guidelines for Individual Contribution

## Quick Overview of (rough) E2E Workflow of our Travel Agent
The flow of this application will be the following:  
Step 1: User Input??  
Step 2: ...  
Step 3: ...  
Step N: ...  

## Team Contribution
The goal of the below I/O mapping is to allow parallel and asynchronous contribution to the repository, while reducing tech debt/churn as much as possible. Each team member has a specified "inputs from other team members" and their own "outputs". These are a rough estimation of the output type of each team member's portion of the code, and the expected output types from other team members if their contribution has dependencies on other team members' work.

## PHASE 1 BUILD INTERFACING AGREEMENT

### **Abid --> Agent E2E Task Running**

Inputs from Michelle:  
- mock tools (func defs.. will allow doc strings to define I/O).  

Inputs from Mohammad:  
- Bool / Description of validated agent plan (type is Bool / String).   
- List of constraints violated (type is List[Any]).   

Outputs:  
- JSON string of the final plan.   

### **Michelle --> Agentic Workflows**  

Inputs from Abid:  
- mock tools (func defs.. will allow doc strings to define I/O).   

Inputs from mohammad:  
- None.   

Outputs:  
- the candidates for the 10 best hotels, restaurants, activities, and flights (List[Dict]).   

### **Mohammad --> Validator Class, Constraint Class, and LLM as a Judge**

Inputs from Abid:  
- JSON string of agent's travel plan.   

Inputs from michelle:  
- None.   

Outputs:  
- Bool / Description of validated agent plan (type is Bool / String).   
- List of constraints violated (type is List[Any]).   

## PHASE 2 BUILD INTERFACING AGREEMENT
*TBD.*   
*POST PROCESSING STEP:*   
*- Natural language interpretation of JSON string outputtted from Abid'ds final step*   