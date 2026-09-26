from pydantic import BaseModel


class PlayerOut(BaseModel):
    id: int
    web_name: str
    position: str
    team_id: int

    model_config = {"from_attributes": True}
