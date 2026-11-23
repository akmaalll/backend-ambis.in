from sqladmin import ModelView
from app.models.learning_path import LearningPath


class LearningPathAdmin(ModelView, model=LearningPath):
    column_list = ["id", "student_id", "subject_id", "status", "created_at"]
    column_searchable_list = ["status"]
    column_sortable_list = ["id", "created_at"]
