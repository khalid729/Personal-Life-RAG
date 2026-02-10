import datetime as dt
from enum import Enum
from typing import Annotated, Optional

from pydantic import BaseModel, Field


# --- Enums ---

class DebtDirection(str, Enum):
    I_OWE = "i_owe"
    OWED_TO_ME = "owed_to_me"


class DebtStatus(str, Enum):
    OPEN = "open"
    PAID = "paid"


class TaskStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class ProjectStatus(str, Enum):
    IDEA = "idea"
    PLANNING = "planning"
    ACTIVE = "active"
    PAUSED = "paused"
    DONE = "done"
    CANCELLED = "cancelled"


class ReminderStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    SNOOZED = "snoozed"


class ReminderType(str, Enum):
    ONE_TIME = "one_time"
    RECURRING = "recurring"


class InputCategory(str, Enum):
    FINANCIAL = "financial"
    REMINDER = "reminder"
    PROJECT = "project"
    SEARCH = "search"
    RELATIONSHIPS = "relationships"
    IDEA = "idea"
    TASK = "task"
    KNOWLEDGE = "knowledge"
    GENERAL = "general"


# --- Entity Schemas ---

class PersonBase(BaseModel):
    name: str
    relationship: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None


class PersonCreate(PersonBase):
    pass


class Person(PersonBase):
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)
    updated_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class CompanyBase(BaseModel):
    name: str
    industry: Optional[str] = None
    notes: Optional[str] = None


class CompanyCreate(CompanyBase):
    pass


class Company(CompanyBase):
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None
    status: ProjectStatus = ProjectStatus.IDEA
    priority: Optional[int] = None
    notes: Optional[str] = None


class ProjectCreate(ProjectBase):
    pass


class Project(ProjectBase):
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)
    updated_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class IdeaBase(BaseModel):
    title: str
    description: Optional[str] = None
    category: Optional[str] = None


class IdeaCreate(IdeaBase):
    pass


class Idea(IdeaBase):
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.TODO
    priority: Optional[int] = None
    due_date: Optional[dt.date] = None
    project: Optional[str] = None


class TaskCreate(TaskBase):
    pass


class Task(TaskBase):
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)
    updated_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class ExpenseBase(BaseModel):
    amount: float
    currency: str = "SAR"
    category: Optional[str] = None
    description: Optional[str] = None
    date: dt.date = Field(default_factory=dt.date.today)
    vendor: Optional[str] = None


class ExpenseCreate(ExpenseBase):
    pass


class Expense(ExpenseBase):
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class DebtBase(BaseModel):
    person: str
    amount: float
    currency: str = "SAR"
    direction: DebtDirection
    reason: Optional[str] = None
    status: DebtStatus = DebtStatus.OPEN
    date: dt.date = Field(default_factory=dt.date.today)


class DebtCreate(DebtBase):
    pass


class Debt(DebtBase):
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class ReminderBase(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[dt.datetime] = None
    status: ReminderStatus = ReminderStatus.PENDING
    reminder_type: ReminderType = ReminderType.ONE_TIME


class ReminderCreate(ReminderBase):
    pass


class Reminder(ReminderBase):
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class KnowledgeBase(BaseModel):
    title: str
    content: str
    source: Optional[str] = None
    category: Optional[str] = None


class KnowledgeCreate(KnowledgeBase):
    pass


class Knowledge(KnowledgeBase):
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class FileBase(BaseModel):
    filename: str
    file_hash: str
    file_type: Optional[str] = None
    size_bytes: Optional[int] = None
    description: Optional[str] = None


class FileCreate(FileBase):
    pass


class File(FileBase):
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class TopicBase(BaseModel):
    name: str
    description: Optional[str] = None


class TopicCreate(TopicBase):
    pass


class Topic(TopicBase):
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class TagBase(BaseModel):
    name: str


class TagCreate(TagBase):
    pass


class Tag(TagBase):
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


# --- API Request/Response Schemas ---

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    reply: str
    sources: list[str] = []
    route: Optional[str] = None


class IngestRequest(BaseModel):
    text: str
    source_type: str = "note"
    tags: list[str] = []
    topic: Optional[str] = None


class IngestResponse(BaseModel):
    status: str
    chunks_stored: int = 0
    facts_extracted: int = 0


class SearchRequest(BaseModel):
    query: str
    source: str = "auto"  # "vector", "graph", "auto"
    limit: int = 5


class SearchResult(BaseModel):
    text: str
    score: float
    source: str
    metadata: dict = {}


class SearchResponse(BaseModel):
    results: list[SearchResult]
    source_used: str


class ExtractedFact(BaseModel):
    entity_type: str
    entity_name: str
    properties: dict = {}
    relationships: list[dict] = []
