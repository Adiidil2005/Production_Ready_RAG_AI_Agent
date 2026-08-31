import pydantic

class RAGChunkAndSrc(pydantic.BaseModel):
    chunks:lists[str]
    source_id=None


class RAGUpsertResult(pydantic.BaseModel):
    ingested:int

class RAGSearchResult(pydantic.BaseModel):
    context:list[str]
    sources:list[str]

class RAGQueryResult(pydantic.BaseModel):
    answer:str
    sources:list[str]
    num_context:int
