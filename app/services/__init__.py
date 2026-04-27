class DiagramAiService:
    def __init__(self) -> None:
        self.openrouter_service = OpenRouterService()
        self.semantic_validator = DiagramSemanticValidator()
        self.auto_repairer = DiagramAiAutoRepairer()