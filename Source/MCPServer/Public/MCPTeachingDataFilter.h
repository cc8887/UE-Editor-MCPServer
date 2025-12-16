// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Templates/SharedPointer.h"

struct FMCPTransactionDiff;
struct FMCPObjectDiff;
struct FMCPPropertyDiff;

/**
 * 示教数据过滤器的抽象基类
 * 用于在停止示教时对收集到的diff数据进行过滤
 * 每种过滤规则都应该继承此类并实现具体的过滤逻辑
 */
class IMCPTeachingDataFilter
{
public:
	virtual ~IMCPTeachingDataFilter() = default;

	/**
	 * 过滤事务级差异数组
	 * @param InOutDiffs 输入输出参数，包含所有事务差异，过滤后会修改此数组
	 */
	virtual void FilterTransactionDiffs(TArray<FMCPTransactionDiff>& InOutDiffs) const = 0;

	/**
	 * 过滤单个事务差异
	 * @param InOutDiff 单个事务差异
	 * @return 如果该事务应该被保留返回true，否则返回false
	 */
	virtual bool FilterSingleTransaction(FMCPTransactionDiff& InOutDiff) const = 0;

	/**
	 * 过滤对象级差异
	 * @param InOutObjectDiffs 对象差异数组
	 */
	virtual void FilterObjectDiffs(TArray<FMCPObjectDiff>& InOutObjectDiffs) const = 0;

	/**
	 * 过滤单个对象差异
	 * @param InOutObjectDiff 单个对象差异
	 * @return 如果该对象差异应该被保留返回true，否则返回false
	 */
	virtual bool FilterSingleObject(FMCPObjectDiff& InOutObjectDiff) const = 0;

	/**
	 * 过滤属性级差异
	 * @param InOutPropertyDiffs 属性差异数组
	 */
	virtual void FilterPropertyDiffs(TArray<FMCPPropertyDiff>& InOutPropertyDiffs) const = 0;

	/**
	 * 过滤单个属性差异
	 * @param InOutPropertyDiff 单个属性差异
	 * @return 如果该属性差异应该被保留返回true，否则返回false
	 */
	virtual bool FilterSingleProperty(FMCPPropertyDiff& InOutPropertyDiff) const = 0;

	/**
	 * 获取过滤器的描述信息
	 */
	virtual FString GetFilterDescription() const = 0;
};

/**
 * 过滤器链管理器
 * 负责管理多个过滤器并按顺序应用它们
 */
class FMCPTeachingDataFilterChain
{
public:
	FMCPTeachingDataFilterChain() = default;

	/**
	 * 添加过滤器到链中
	 * @param Filter 要添加的过滤器
	 */
	void AddFilter(TSharedPtr<IMCPTeachingDataFilter> Filter);

	/**
	 * 移除所有过滤器
	 */
	void ClearFilters();

	/**
	 * 应用所有过滤器到事务差异数组
	 * @param InOutDiffs 要过滤的事务差异数组
	 */
	void ApplyFilters(TArray<FMCPTransactionDiff>& InOutDiffs) const;

	/**
	 * 获取当前过滤器数量
	 */
	int32 GetFilterCount() const { return Filters.Num(); }

	/**
	 * 获取所有过滤器的描述信息
	 */
	TArray<FString> GetFilterDescriptions() const;

private:
	TArray<TSharedPtr<IMCPTeachingDataFilter>> Filters;
};

/**
 * 基础过滤器实现，提供默认的过滤逻辑
 * 子类可以选择性地重写需要的方法
 */
class FMCPTeachingDataFilterBase : public IMCPTeachingDataFilter
{
public:
	virtual ~FMCPTeachingDataFilterBase() = default;

	// 默认实现：遍历所有事务并调用FilterSingleTransaction
	virtual void FilterTransactionDiffs(TArray<FMCPTransactionDiff>& InOutDiffs) const override;

	// 默认实现：过滤对象差异，然后检查是否还有差异
	virtual bool FilterSingleTransaction(FMCPTransactionDiff& InOutDiff) const override;

	// 默认实现：遍历所有对象并调用FilterSingleObject
	virtual void FilterObjectDiffs(TArray<FMCPObjectDiff>& InOutObjectDiffs) const override;

	// 默认实现：过滤属性差异，然后检查是否还有差异
	virtual bool FilterSingleObject(FMCPObjectDiff& InOutObjectDiff) const override;

	// 默认实现：遍历所有属性并调用FilterSingleProperty
	virtual void FilterPropertyDiffs(TArray<FMCPPropertyDiff>& InOutPropertyDiffs) const override;

	// 默认实现：保留所有属性
	virtual bool FilterSingleProperty(FMCPPropertyDiff& InOutPropertyDiff) const override;

	virtual FString GetFilterDescription() const override;
};

/**
 * 蓝图对象过滤器
 * 过滤掉UBlueprint资源对象的差异，只保留蓝图生成的实例对象（如Actor、Component等）的变化
 * 用于示教时只关注实际游戏对象的变化，而不关心蓝图资源本身的变化
 */
class FMCPBlueprintObjectFilter : public FMCPTeachingDataFilterBase
{
public:
	FMCPBlueprintObjectFilter() = default;

	// IMCPTeachingDataFilter 接口实现
	virtual bool FilterSingleObject(FMCPObjectDiff& InOutObjectDiff) const override;
	virtual FString GetFilterDescription() const override;
};

/**
 * 蓝图可编辑属性过滤器
 * 只保留在蓝图中可修改的属性变化（具有BlueprintReadWrite、EditAnywhere等可写标记的属性）
 * 过滤掉只读属性（BlueprintReadOnly、VisibleAnywhere等）和内部实现细节
 * 
 * 白名单机制：仅对以下类型的对象启用属性过滤
 * - AActor 及其子类
 * - UActorComponent 及其子类
 * - UGameplayAbility 及其子类
 * 
 * 对于不在白名单中的对象类型，将保留所有属性差异
 * 用于示教时只关注用户可以在蓝图中实际修改的属性
 */
class FMCPBlueprintVisiblePropertyFilter : public FMCPTeachingDataFilterBase
{
public:
	FMCPBlueprintVisiblePropertyFilter() = default;

	// IMCPTeachingDataFilter 接口实现
	virtual bool FilterSingleObject(FMCPObjectDiff& InOutObjectDiff) const override;
	virtual FString GetFilterDescription() const override;
};
