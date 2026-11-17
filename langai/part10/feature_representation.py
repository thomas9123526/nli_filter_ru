from sklearn.feature_extraction.text import TfidfVectorizer

documents = [
    # Sports (label 0)
    "The team won the championship with a decisive victory in the final game",
    "Baseball scores improved as the pitcher dominated the field all season long",
    "Soccer players celebrated after winning the league title with stunning goals",
    # Politics (label 1)
    "The senator voted against the new healthcare legislation in congress",
    "Presidential candidates debated economic policy and foreign affairs last week",
    "Government officials announced new regulations for environmental protection",
    # Technology (label 2)
    "The new machine learning framework outperforms previous models on benchmarks",
    "Software engineers deployed the neural network to the cloud computing platform",
    "Deep learning algorithms process natural language with impressive accuracy",
]

labels = [0, 0, 0, 1, 1, 1, 2, 2, 2]
class_names_str = ["sports", "politics", "technology"]

vectorizer = TfidfVectorizer(max_features=30, stop_words="english")
X = vectorizer.fit_transform(documents).toarray()
vocab = vectorizer.get_feature_names_out()