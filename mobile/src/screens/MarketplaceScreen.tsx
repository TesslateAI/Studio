import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  ActivityIndicator,
  SafeAreaView,
  TextInput,
  ScrollView,
  Image,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../theme/ThemeContext';
import { marketplaceApi } from '../lib/api';
import Toast from 'react-native-toast-message';

interface MarketplaceAgent {
  id: string;
  name: string;
  slug: string;
  description?: string;
  icon: string;
  category?: string;
  pricing_type?: string;
  price?: number;
  features?: string[];
  is_purchased?: boolean;
}

const MarketplaceScreen: React.FC = () => {
  const { theme } = useTheme();
  const [agents, setAgents] = useState<MarketplaceAgent[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('all');

  const categories = [
    'all',
    'coding',
    'design',
    'writing',
    'data',
    'automation',
    'other',
  ];

  useEffect(() => {
    fetchAgents();
  }, []);

  const fetchAgents = async () => {
    try {
      const data = await marketplaceApi.getAllAgents();
      setAgents(data);
    } catch (error) {
      console.error('Failed to fetch agents:', error);
      Toast.show({
        type: 'error',
        text1: 'Error',
        text2: 'Failed to load marketplace',
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handlePurchase = async (agentId: string, agentName: string) => {
    try {
      await marketplaceApi.purchaseAgent(agentId);
      Toast.show({
        type: 'success',
        text1: 'Success',
        text2: `${agentName} added to your library`,
      });
      fetchAgents();
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail || 'Failed to purchase agent';
      Toast.show({
        type: 'error',
        text1: 'Purchase Failed',
        text2: errorMessage,
      });
    }
  };

  // Filter agents
  const filteredAgents = agents.filter((agent) => {
    const matchesSearch =
      searchQuery === '' ||
      agent.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      agent.description?.toLowerCase().includes(searchQuery.toLowerCase());

    const matchesCategory =
      selectedCategory === 'all' || agent.category === selectedCategory;

    return matchesSearch && matchesCategory;
  });

  const renderAgent = ({ item }: { item: MarketplaceAgent }) => (
    <TouchableOpacity
      style={[styles.agentCard, { backgroundColor: theme.card, borderColor: theme.border }]}
    >
      <View style={styles.agentHeader}>
        <View style={[styles.iconContainer, { backgroundColor: theme.primaryLight }]}>
          <Text style={styles.iconText}>{item.icon || '🤖'}</Text>
        </View>
        <View style={styles.agentInfo}>
          <Text style={[styles.agentName, { color: theme.text }]} numberOfLines={1}>
            {item.name}
          </Text>
          {item.category && (
            <Text style={[styles.agentCategory, { color: theme.textTertiary }]}>
              {item.category}
            </Text>
          )}
        </View>
      </View>

      {item.description && (
        <Text style={[styles.agentDescription, { color: theme.textSecondary }]} numberOfLines={2}>
          {item.description}
        </Text>
      )}

      {item.features && item.features.length > 0 && (
        <View style={styles.features}>
          {item.features.slice(0, 3).map((feature, index) => (
            <View
              key={index}
              style={[styles.featureBadge, { backgroundColor: theme.backgroundSecondary }]}
            >
              <Text style={[styles.featureText, { color: theme.textSecondary }]}>
                {feature}
              </Text>
            </View>
          ))}
        </View>
      )}

      <View style={styles.agentFooter}>
        <View style={styles.pricing}>
          {item.pricing_type === 'free' ? (
            <Text style={[styles.priceText, { color: theme.success }]}>FREE</Text>
          ) : (
            <Text style={[styles.priceText, { color: theme.text }]}>
              ${item.price || 0}/mo
            </Text>
          )}
        </View>

        {item.is_purchased ? (
          <View style={[styles.purchasedBadge, { backgroundColor: theme.successLight }]}>
            <Ionicons name="checkmark-circle" size={16} color={theme.success} />
            <Text style={[styles.purchasedText, { color: theme.success }]}>Owned</Text>
          </View>
        ) : (
          <TouchableOpacity
            style={[styles.purchaseButton, { backgroundColor: theme.primary }]}
            onPress={() => handlePurchase(item.id, item.name)}
          >
            <Text style={styles.purchaseButtonText}>
              {item.pricing_type === 'free' ? 'Add' : 'Purchase'}
            </Text>
          </TouchableOpacity>
        )}
      </View>
    </TouchableOpacity>
  );

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: theme.background }]}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={[styles.headerTitle, { color: theme.text }]}>Marketplace</Text>
        <Text style={[styles.headerSubtitle, { color: theme.textSecondary }]}>
          Discover AI agents
        </Text>
      </View>

      {/* Search */}
      <View style={[styles.searchContainer, { backgroundColor: theme.backgroundSecondary }]}>
        <Ionicons name="search" size={20} color={theme.textTertiary} />
        <TextInput
          style={[styles.searchInput, { color: theme.text }]}
          placeholder="Search agents..."
          placeholderTextColor={theme.textTertiary}
          value={searchQuery}
          onChangeText={setSearchQuery}
        />
      </View>

      {/* Categories */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.categoriesContainer}
        contentContainerStyle={styles.categoriesContent}
      >
        {categories.map((category) => (
          <TouchableOpacity
            key={category}
            style={[
              styles.categoryChip,
              {
                backgroundColor:
                  selectedCategory === category ? theme.primary : theme.backgroundSecondary,
              },
            ]}
            onPress={() => setSelectedCategory(category)}
          >
            <Text
              style={[
                styles.categoryText,
                {
                  color: selectedCategory === category ? '#FFFFFF' : theme.text,
                },
              ]}
            >
              {category.charAt(0).toUpperCase() + category.slice(1)}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {/* Agents List */}
      {isLoading ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={theme.primary} />
        </View>
      ) : (
        <FlatList
          data={filteredAgents}
          renderItem={renderAgent}
          keyExtractor={(item) => item.id}
          contentContainerStyle={styles.listContent}
          numColumns={2}
          columnWrapperStyle={styles.row}
          ListEmptyComponent={
            <View style={styles.emptyState}>
              <Ionicons name="search-outline" size={64} color={theme.textTertiary} />
              <Text style={[styles.emptyText, { color: theme.textSecondary }]}>
                No agents found
              </Text>
            </View>
          }
        />
      )}
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    padding: 20,
  },
  headerTitle: {
    fontSize: 28,
    fontWeight: 'bold',
  },
  headerSubtitle: {
    fontSize: 14,
    marginTop: 4,
  },
  searchContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginHorizontal: 20,
    marginBottom: 16,
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 12,
  },
  searchInput: {
    flex: 1,
    marginLeft: 12,
    fontSize: 16,
  },
  categoriesContainer: {
    marginHorizontal: 20,
    marginBottom: 16,
  },
  categoriesContent: {
    gap: 8,
  },
  categoryChip: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
  },
  categoryText: {
    fontSize: 14,
    fontWeight: '600',
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  listContent: {
    padding: 20,
  },
  row: {
    justifyContent: 'space-between',
  },
  agentCard: {
    width: '48%',
    padding: 16,
    borderRadius: 12,
    marginBottom: 16,
    borderWidth: 1,
  },
  agentHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  iconContainer: {
    width: 40,
    height: 40,
    borderRadius: 20,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  iconText: {
    fontSize: 20,
  },
  agentInfo: {
    flex: 1,
  },
  agentName: {
    fontSize: 16,
    fontWeight: '600',
  },
  agentCategory: {
    fontSize: 12,
    marginTop: 2,
    textTransform: 'capitalize',
  },
  agentDescription: {
    fontSize: 13,
    marginBottom: 12,
    lineHeight: 18,
  },
  features: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginBottom: 12,
  },
  featureBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
  },
  featureText: {
    fontSize: 11,
  },
  agentFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  pricing: {},
  priceText: {
    fontSize: 16,
    fontWeight: 'bold',
  },
  purchasedBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 16,
  },
  purchasedText: {
    fontSize: 12,
    fontWeight: '600',
  },
  purchaseButton: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 8,
  },
  purchaseButtonText: {
    color: '#FFFFFF',
    fontSize: 13,
    fontWeight: '600',
  },
  emptyState: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingTop: 60,
  },
  emptyText: {
    fontSize: 16,
    marginTop: 16,
  },
});

export default MarketplaceScreen;
