# domain -> {parent skill: [child skills]}  (children may themselves be parents)
DOMAINS = {
 "Web": {"Web Development": ["Frontend", "Backend"],
         "Frontend": ["React", "Vue", "Angular", "HTML/CSS", "Tailwind CSS"],
         "Backend": ["Node.js", "Django", "Flask", "Spring Boot", "REST APIs"]},
 "Data": {"Data Science": ["Machine Learning", "Data Analysis", "Data Engineering"],
          "Machine Learning": ["PyTorch", "TensorFlow", "Scikit-learn", "NLP", "Computer Vision"],
          "Data Analysis": ["Pandas", "SQL", "Tableau", "Excel"],
          "Data Engineering": ["Apache Spark", "Airflow", "ETL", "PostgreSQL"]},
 "Mobile": {"Mobile Development": ["Android", "iOS", "Cross-platform"], "Android": ["Kotlin", "Jetpack Compose"],
            "iOS": ["Swift", "SwiftUI"], "Cross-platform": ["Flutter", "React Native"]},
 "Design": {"Design": ["UI Design", "Graphic Design", "Motion Design"],
            "UI Design": ["Figma", "Wireframing", "Design Systems"],
            "Graphic Design": ["Photoshop", "Illustrator", "Branding"],
            "Motion Design": ["After Effects", "Video Editing"]},
 "Cloud": {"Cloud & DevOps": ["AWS", "DevOps", "Cybersecurity"], "AWS": ["EC2", "S3", "Lambda"],
           "DevOps": ["Docker", "Kubernetes", "CI/CD", "Terraform"],
           "Cybersecurity": ["Penetration Testing", "Network Security"]},
 "Writing": {"Content": ["Copywriting", "Technical Writing", "Translation"],
             "Copywriting": ["SEO Writing", "Ad Copy"], "Technical Writing": ["API Documentation", "User Manuals"]},
 "Marketing": {"Digital Marketing": ["SEO", "Social Media", "Email Marketing"],
               "SEO": ["Keyword Research", "Link Building"],
               "Social Media": ["Instagram Marketing", "Content Calendars"]},
 "Finance": {"Finance": ["Accounting", "Financial Modeling"],
             "Accounting": ["Bookkeeping", "Tax Filing", "QuickBooks"],
             "Financial Modeling": ["Valuation", "Forecasting"]},
}
# Skills deliberately NOT linked in the graph: only semantic search can connect them
# (e.g. "Server-side JavaScript" ~ "Node.js").
SYNONYMS = {
 "Web": ["Server-side JavaScript", "Single-page application development", "Responsive website building"],
 "Data": ["Deep neural networks", "Predictive modelling", "Text mining"],
 "Mobile": ["Native app development", "Smartphone application building"],
 "Design": ["Visual interface design", "Logo creation"],
 "Cloud": ["Cloud infrastructure automation", "Container orchestration"],
 "Writing": ["Blog article writing", "Product documentation"],
 "Marketing": ["Search engine ranking", "Online brand promotion"],
 "Finance": ["Company books management", "Budget projection"],
}

def domain_skills(d):
    s = set(DOMAINS[d]) | {c for v in DOMAINS[d].values() for c in v} | set(SYNONYMS[d])
    return sorted(s)
