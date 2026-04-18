from typing import Literal

from pydantic import BaseModel, Field


class CharIndex(BaseModel):
    start: int = Field(..., ge=0, description="原文起始下标")
    end: int = Field(..., ge=0, description="原文结束下标")


class AuditResult(BaseModel):
    risk_level: Literal["低", "中", "高", "严重"] = Field(..., description="风险等级")
    audit_item: str = Field(..., description="审核项")
    risk_description: str = Field(..., description="风险提示")
    original_quote: str = Field(..., description="精确的原文引用")
    char_index: CharIndex = Field(..., description="用于前端高亮定位的字符坐标")
    suggestion: str = Field(..., description="修改建议")


class CompareResult(BaseModel):
    change_type: Literal["新增", "修改", "删除"] = Field(..., description="变更性质")
    base_content: str = Field(..., description="原条款内容")
    current_content: str = Field(..., description="新条款内容")
    impact_analysis: str = Field(..., description="该变更对合同风险的影响分析")
    base_index: CharIndex = Field(..., description="旧版本字符坐标")
    current_index: CharIndex = Field(..., description="新版本字符坐标")
