// Copyright Epic Games, Inc. All Rights Reserved.

#include "MCPTeachingDataFilter.h"
#include "MCPTeachingSessionManager.h"
#include "MCPServer.h"
#include "MCPObjectInformDumpLibrary.h"

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

bool FMCPBlueprintVisiblePropertyFilter::FilterSingleObject(FMCPObjectDiff& InOutObjectDiff) const
{
	// 白名单检查：仅对特定类型的对象启用属性过滤
	// 检查对象类名是否为白名单中的类型或其子类
	const FString& ObjectClass = InOutObjectDiff.ObjectClass;
	
	bool bShouldFilterProperties = false;
	
	// 检查是否是 Actor 类型（包含 Actor 关键字，如 Actor, StaticMeshActor, Character 等）
	// 注意：蓝图生成的Actor类名通常包含 _C 后缀
	if (ObjectClass.Contains(TEXT("Actor")) || 
		ObjectClass.EndsWith(TEXT("_C")))  // 蓝图生成类
	{
		bShouldFilterProperties = true;
	}
	// 检查是否是 ActorComponent 类型
	else if (ObjectClass.Contains(TEXT("Component")))
	{
		bShouldFilterProperties = true;
	}
	// 检查是否是 GameplayAbility 类型
	else if (ObjectClass.Contains(TEXT("GameplayAbility")) || 
			 ObjectClass.Contains(TEXT("Ability")))
	{
		bShouldFilterProperties = true;
	}
	
	// 如果不在白名单中，保留所有属性差异，直接返回
	if (!bShouldFilterProperties)
	{
		return InOutObjectDiff.HasDifferences();
	}
	
	// 在白名单中的对象，需要过滤属性
	// 尝试找到对应的UObject来检查属性元数据
	UObject* FoundObject = FindObject<UObject>(nullptr, *InOutObjectDiff.ObjectPath);
	
	if (!FoundObject)
	{
		// 如果找不到对象，尝试加载
		FoundObject = LoadObject<UObject>(nullptr, *InOutObjectDiff.ObjectPath);
	}
	
	if (FoundObject)
	{
		UClass* ObjectClassPtr = FoundObject->GetClass();
		
		// 从后向前遍历，以便安全地移除元素
		for (int32 i = InOutObjectDiff.PropertyDiffs.Num() - 1; i >= 0; --i)
		{
			const FMCPPropertyDiff& PropDiff = InOutObjectDiff.PropertyDiffs[i];
			
			// 查找属性
			FProperty* Property = ObjectClassPtr->FindPropertyByName(PropDiff.PropertyName);
			
			if (Property)
			{
				// 使用已有的工具函数检查属性是否可编辑
				if (!UMCPObjectInformDumpLibrary::IsBlueprintEditable(Property))
				{
					UE_LOG(LogMCPServer, Verbose, TEXT("Filtering non-editable property: %s.%s"), 
						*ObjectClass, *PropDiff.PropertyName.ToString());
					InOutObjectDiff.PropertyDiffs.RemoveAt(i);
				}
			}
			else
			{
				// 找不到属性定义时，保守起见保留该差异
				UE_LOG(LogMCPServer, Verbose, TEXT("Property not found in class, keeping: %s.%s"), 
					*ObjectClass, *PropDiff.PropertyName.ToString());
			}
		}
	}
	else
	{
		// 找不到对象时，使用属性名称启发式过滤
		// 过滤掉常见的内部属性
		for (int32 i = InOutObjectDiff.PropertyDiffs.Num() - 1; i >= 0; --i)
		{
			const FMCPPropertyDiff& PropDiff = InOutObjectDiff.PropertyDiffs[i];
			const FString PropName = PropDiff.PropertyName.ToString();
			
			// 过滤掉以下划线开头的内部属性
			if (PropName.StartsWith(TEXT("_")))
			{
				InOutObjectDiff.PropertyDiffs.RemoveAt(i);
				continue;
			}
			
			// 过滤掉常见的只读/内部属性
			static const TArray<FString> InternalPropertyPrefixes = {
				TEXT("b"),       // 布尔标记（很多是内部标记）
				TEXT("Cached"), 
				TEXT("Last"),
				TEXT("Prev"),
				TEXT("Old"),
				TEXT("Internal"),
				TEXT("Native")
			};
			
			// 这里采用保守策略，不做过多的启发式过滤
			// 因为无法获取到实际的属性元数据
		}
	}
	
	return InOutObjectDiff.HasDifferences();
}

FString FMCPBlueprintVisiblePropertyFilter::GetFilterDescription() const
{
	return TEXT("Blueprint Visible Property Filter (keeps only blueprint-editable properties for Actor/Component/Ability objects)");
}
