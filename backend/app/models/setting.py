from typing import Optional
from sqlmodel import Field, SQLModel

class SystemSetting(SQLModel, table=True):
    key: str = Field(primary_key=True, index=True)
    value: str
    description: Optional[str] = None
