// Copyright Epic Games, Inc. All Rights Reserved.

#include "MCPTeachingDataFilter.h"
#include "MCPTeachingSessionManager.h"
#include "MCPServer.h"

// ============================================================================
// FMCPTeachingDataFilterChain 实现
// ============================================================================

void FMCPTeachingDataFilterChain::AddFilter(TSharedPtr<IMCPTeachingDataFilter> Filter)
{
	if (Filter.IsValid())
	{
		Filters.Add(Filter);
		UE_LOG(LogMCPServer, Log, TEXT("Added filter to chain: %s"), *Filter->GetFilterDescription());
	}
}

void FMCPTeachingDataFilterChain::ClearFilters()
{
	Filters.Empty();
	UE_LOG(LogMCPServer, Log, TEXT("Cleared all filters from chain"));
}

void FMCPTeachingDataFilterChain::ApplyFilters(TArray<FMCPTransactionDiff>& InOutDiffs) const
{
	if (Filters.Num() == 0)
	{
		UE_LOG(LogMCPServer, Verbose, TEXT("No filters to apply"));
		return;
	}

	UE_LOG(LogMCPServer, Log, TEXT("Applying %d filters to %d transactions"), Filters.Num(), InOutDiffs.Num());

	// 按顺序应用每个过滤器
	for (const TSharedPtr<IMCPTeachingDataFilter>& Filter : Filters)
	{
		if (Filter.IsValid())
		{
			const int32 BeforeCount = InOutDiffs.Num();
			Filter->FilterTransactionDiffs(InOutDiffs);
			const int32 AfterCount = InOutDiffs.Num();
			
			UE_LOG(LogMCPServer, Verbose, TEXT("Filter '%s' processed: %d -> %d transactions"), 
				*Filter->GetFilterDescription(), BeforeCount, AfterCount);
		}
	}

	UE_LOG(LogMCPServer, Log, TEXT("Filter chain complete. Final transaction count: %d"), InOutDiffs.Num());
}

TArray<FString> FMCPTeachingDataFilterChain::GetFilterDescriptions() const
{
	TArray<FString> Descriptions;
	for (const TSharedPtr<IMCPTeachingDataFilter>& Filter : Filters)
	{
		if (Filter.IsValid())
		{
			Descriptions.Add(Filter->GetFilterDescription());
		}
	}
	return Descriptions;
}

// ============================================================================
// FMCPTeachingDataFilterBase 实现
// ============================================================================

void FMCPTeachingDataFilterBase::FilterTransactionDiffs(TArray<FMCPTransactionDiff>& InOutDiffs) const
{
	// 从后向前遍历，以便安全地移除元素
	for (int32 i = InOutDiffs.Num() - 1; i >= 0; --i)
	{
		if (!FilterSingleTransaction(InOutDiffs[i]))
		{
			InOutDiffs.RemoveAt(i);
		}
	}
}

bool FMCPTeachingDataFilterBase::FilterSingleTransaction(FMCPTransactionDiff& InOutDiff) const
{
	// 先过滤对象差异
	FilterObjectDiffs(InOutDiff.ObjectDiffs);
	
	// 如果过滤后没有差异了，则移除整个事务
	return InOutDiff.HasDifferences();
}

void FMCPTeachingDataFilterBase::FilterObjectDiffs(TArray<FMCPObjectDiff>& InOutObjectDiffs) const
{
	// 从后向前遍历，以便安全地移除元素
	for (int32 i = InOutObjectDiffs.Num() - 1; i >= 0; --i)
	{
		if (!FilterSingleObject(InOutObjectDiffs[i]))
		{
			InOutObjectDiffs.RemoveAt(i);
		}
	}
}

bool FMCPTeachingDataFilterBase::FilterSingleObject(FMCPObjectDiff& InOutObjectDiff) const
{
	// 先过滤属性差异
	FilterPropertyDiffs(InOutObjectDiff.PropertyDiffs);
	
	// 如果过滤后没有差异了，则移除整个对象
	return InOutObjectDiff.HasDifferences();
}

void FMCPTeachingDataFilterBase::FilterPropertyDiffs(TArray<FMCPPropertyDiff>& InOutPropertyDiffs) const
{
	// 从后向前遍历，以便安全地移除元素
	for (int32 i = InOutPropertyDiffs.Num() - 1; i >= 0; --i)
	{
		if (!FilterSingleProperty(InOutPropertyDiffs[i]))
		{
			InOutPropertyDiffs.RemoveAt(i);
		}
	}
}

bool FMCPTeachingDataFilterBase::FilterSingleProperty(FMCPPropertyDiff& InOutPropertyDiff) const
{
	// 默认保留所有属性
	return true;
}

FString FMCPTeachingDataFilterBase::GetFilterDescription() const
{
	return TEXT("Base Filter (No filtering)");
}

// ============================================================================
// FMCPBlueprintObjectFilter 实现
// ============================================================================

bool FMCPBlueprintObjectFilter::FilterSingleObject(FMCPObjectDiff& InOutObjectDiff) const
{
	// 检查对象类名是否为UBlueprint或其子类
	// UBlueprint的常见子类包括：UBlueprint, UAnimBlueprint, UWidgetBlueprint等
	if (InOutObjectDiff.ObjectClass.Contains(TEXT("Blueprint")))
	{
		// 进一步检查是否确实是Blueprint资源对象
		// Blueprint对象的路径通常包含 .uasset 或在 /Game/ 等内容目录下
		// 而蓝图生成的实例对象路径通常在 /Engine/Transient/ 或关卡中
		
		// 如果对象路径不包含 _C (GeneratedClass后缀)，很可能是Blueprint资源本身
		if (!InOutObjectDiff.ObjectPath.Contains(TEXT("_C")))
		{
			UE_LOG(LogMCPServer, Verbose, TEXT("Filtering Blueprint object: %s (class: %s)"), 
				*InOutObjectDiff.ObjectPath, *InOutObjectDiff.ObjectClass);
			return false;
		}
	}
	
	// 否则继续过滤属性差异
	return FMCPTeachingDataFilterBase::FilterSingleObject(InOutObjectDiff);
}

FString FMCPBlueprintObjectFilter::GetFilterDescription() const
{
	return TEXT("Blueprint Object Filter (removes UBlueprint asset changes, keeps instance changes)");
}
