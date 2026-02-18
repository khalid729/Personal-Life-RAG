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
    PARTIAL = "partial"
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
    PERSISTENT = "persistent"
    EVENT_BASED = "event_based"
    FINANCIAL = "financial"


class Recurrence(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class EnergyLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SprintStatus(str, Enum):
    PLANNING = "planning"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


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


class FileType(str, Enum):
    INVOICE = "invoice"
    OFFICIAL_DOCUMENT = "official_document"
    PERSONAL_PHOTO = "personal_photo"
    INFO_IMAGE = "info_image"
    NOTE = "note"
    PROJECT_FILE = "project_file"
    PRICE_LIST = "price_list"
    BUSINESS_CARD = "business_card"
    PDF_DOCUMENT = "pdf_document"
    AUDIO_RECORDING = "audio_recording"
    INVENTORY_ITEM = "inventory_item"


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
    estimated_duration: Optional[int] = None  # minutes
    energy_level: Optional[str] = None  # high/medium/low
    start_time: Optional[dt.datetime] = None  # scheduled start
    end_time: Optional[dt.datetime] = None  # scheduled end


class TaskCreate(TaskBase):
    pass


class Task(TaskBase):
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)
    updated_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class SprintBase(BaseModel):
    name: str
    start_date: Optional[dt.date] = None
    end_date: Optional[dt.date] = None
    goal: Optional[str] = None
    status: SprintStatus = SprintStatus.PLANNING
    project: Optional[str] = None


class Sprint(SprintBase):
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)
    velocity: Optional[float] = None


class FocusSessionCreate(BaseModel):
    task: Optional[str] = None
    duration_minutes: int = 25


class FocusStatsResponse(BaseModel):
    today_sessions: int = 0
    today_minutes: int = 0
    week_sessions: int = 0
    week_minutes: int = 0
    total_sessions: int = 0
    total_minutes: int = 0
    by_task: list[dict] = []


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
    priority: Optional[int] = None
    recurrence: Optional[Recurrence] = None
    snooze_count: int = 0
    trigger_event: Optional[str] = None
    linked_entity: Optional[str] = None


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
    agentic_trace: list[dict] = []
    tool_calls: list[dict] = []


class IngestRequest(BaseModel):
    text: str
    source_type: str = "note"
    tags: list[str] = []
    topic: Optional[str] = None


class IngestResponse(BaseModel):
    status: str
    chunks_stored: int = 0
    facts_extracted: int = 0
    entities: list[dict] = []


class URLIngestRequest(BaseModel):
    url: str
    context: str = ""
    tags: list[str] = []
    topic: Optional[str] = None


class FileUploadResponse(BaseModel):
    status: str
    filename: str
    file_type: Optional[str] = None
    file_hash: str = ""
    analysis: dict = {}
    chunks_stored: int = 0
    facts_extracted: int = 0
    processing_steps: list[str] = []
    auto_expense: Optional[dict] = None
    auto_item: Optional[dict] = None
    entities: list[dict] = []


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


# --- Financial / Reminder Request/Response ---

class FinancialReportRequest(BaseModel):
    month: Optional[int] = None
    year: Optional[int] = None
    compare: bool = False


class CategorySummary(BaseModel):
    category: str
    total: float
    count: int
    percentage: float


class MonthlyReport(BaseModel):
    month: int
    year: int
    total: float
    currency: str = "SAR"
    by_category: list[CategorySummary] = []
    comparison: Optional[dict] = None


class DebtSummaryResponse(BaseModel):
    total_i_owe: float
    total_owed_to_me: float
    net_position: float
    debts: list[dict] = []


class DebtPaymentRequest(BaseModel):
    person: str
    amount: float
    direction: Optional[str] = None


class ReminderActionRequest(BaseModel):
    title: str
    action: str  # "done", "snooze", "cancel"
    snooze_until: Optional[dt.datetime] = None


class ReminderUpdateRequest(BaseModel):
    title: str
    new_title: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[int] = None
    description: Optional[str] = None
    recurrence: Optional[str] = None


class ReminderDeleteRequest(BaseModel):
    title: Optional[str] = None
    node_id: Optional[int] = None
    status: Optional[str] = None  # for bulk delete by status


class ProjectUpdateRequest(BaseModel):
    name: str
    status: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[int] = None


class ProjectDeleteRequest(BaseModel):
    name: str


class ProjectMergeRequest(BaseModel):
    sources: list[str]  # project names to merge FROM
    target: str  # project name to merge INTO


class TaskUpdateRequest(BaseModel):
    title: str
    new_title: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[int] = None
    project: Optional[str] = None


class TaskDeleteRequest(BaseModel):
    title: str


# --- Inventory ---

class InventoryItemRequest(BaseModel):
    name: str
    quantity: int = 1
    location: Optional[str] = None
    category: Optional[str] = None
    condition: Optional[str] = None
    brand: Optional[str] = None
    description: Optional[str] = None


class InventoryLocationUpdate(BaseModel):
    location: str


class InventoryQuantityUpdate(BaseModel):
    quantity: int


# --- Productivity (Phase 10) ---

class SprintCreateRequest(BaseModel):
    name: str
    project: Optional[str] = None
    start_date: Optional[str] = None  # YYYY-MM-DD
    end_date: Optional[str] = None  # YYYY-MM-DD
    goal: Optional[str] = None


class SprintUpdateRequest(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    goal: Optional[str] = None


class TimeBlockRequest(BaseModel):
    date: str  # YYYY-MM-DD
    energy_override: Optional[str] = None  # "normal", "tired", "energized"


class TimeBlockResponse(BaseModel):
    blocks: list[dict] = []
    energy_profile: str = "normal"
    date: str = ""


class FocusStartRequest(BaseModel):
    task: Optional[str] = None
    duration_minutes: int = 25


class FocusCompleteRequest(BaseModel):
    completed: bool = True
