from quadrant_client import QdrantClient
from qdrant_client.models import VectorParams,Distance,PointStruct
from urllib3.util import timeout


class QdrantStorage:
    def __init__(self,url="http://localhost:6333",collection="docs",dim=3072):
        self.client = QdrantClient(url=url,timeout=30)
        self.collection = collection
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=dim,distance=Distance.COSINE),

            )

    def upsert(self,ids,vectors,payload):
        points=[PointStruct(id=ids[i],vector=vectors[i],payload=payload) for i in range(len(ids))]
        self.client.upsert(self.collection,points=points)

    def search(self,query_vectors,top_k:int=5):
        results = self.client.search(
            collection_name=self.collection,
            query_vectors=query_vectors,
            with_payloads=True,
            limit=top_k,
        )

        contexts=[]
        sources=set()

        for r in results:
            payload=getattr(r,"payload",None) or {}
            text=payload.get("text","")
            source=payload.get("source","")
            if text:
                contexts.append(text)
                sources.add(source)
        return {"contexts":contexts,"sources":list(sources)}
