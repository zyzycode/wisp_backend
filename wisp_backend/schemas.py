from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1)
    messages: list[dict[str, JsonValue]] = Field(min_length=1)
    stream: StrictBool = False


