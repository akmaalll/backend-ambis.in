from sqladmin import ModelView
from app.models.learning_path import LearningPathModel


class LearningPathAdmin(ModelView, model=LearningPathModel):
    column_list = ["id", "title", "topic", "difficulty", "created_at"]
    column_searchable_list = ["title", "topic"]
    column_sortable_list = ["id", "created_at"]
